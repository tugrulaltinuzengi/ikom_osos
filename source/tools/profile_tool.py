#!/usr/bin/env python3
"""Manage meter profiles from the command line.

    python profile_tool.py validate ../meter-profiles/examples/sdm630.json
    python profile_tool.py push     ../meter-profiles/examples/sdm630.json --modem gw-01 --assign an-02
    python profile_tool.py list     --modem gw-01
    python profile_tool.py assign   --modem gw-01 --analyzer an-02 --profile sdm630
    python profile_tool.py test     --modem gw-01 --analyzer an-02 --address 70 --fc 4 --type f32
    python profile_tool.py delete   --modem gw-01 --profile sdm630

`validate` needs no broker. Everything else talks to the modem over MQTT like the
phone does: each upload message is acked by the gateway before the next is sent,
and the first refusal stops the upload (the gateway keeps its old profile).

Connection flags are the same as meter_cmd.py (--host --port --tls --user --pass).
Exit codes: 0 ok, 1 invalid profile, 2 gateway refused, 3 no answer.
"""
import argparse
import json
import ssl
import sys
import threading
import time

import meterprofile as mp
import osos_proto as p


class Link:
    """Send commands to one modem and wait for each ack."""

    def __init__(self, args):
        import paho.mqtt.client as mqtt
        self.mid = args.modem
        self.timeout = args.timeout
        self.acks = {}
        self.retained = {}
        self.cv = threading.Condition()
        self.cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"profile-tool-{int(time.time())}")
        if args.user:
            self.cl.username_pw_set(args.user, args.password)
        port = args.port or (8883 if args.tls else 1883)
        if args.tls:
            self.cl.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.cl.on_message = self._on_message
        self.cl.on_connect = lambda cl, *_: cl.subscribe(
            [(p.modem_topic(self.mid, "ack"), 1), (p.modem_topic(self.mid, "profiles"), 1)])
        self.cl.connect(args.host, port, keepalive=30)
        self.cl.loop_start()

    def _on_message(self, cl, _u, msg):
        try:
            body = json.loads(msg.payload)
        except ValueError:
            return
        with self.cv:
            if msg.topic.endswith("/ack"):
                self.acks[body.get("id")] = body
            else:
                self.retained[msg.topic] = body
            self.cv.notify_all()

    def send(self, action, args):
        cid = f"pt-{time.time_ns() // 1000:x}"
        self.cl.publish(p.modem_topic(self.mid, "cmd"),
                        json.dumps({"id": cid, "action": action, "args": args}), qos=1)
        deadline = time.time() + self.timeout
        with self.cv:
            while cid not in self.acks:
                left = deadline - time.time()
                if left <= 0:
                    return None
                self.cv.wait(left)
            return self.acks.pop(cid)

    def profiles(self, wait=3.0):
        topic = p.modem_topic(self.mid, "profiles")
        deadline = time.time() + wait
        with self.cv:
            while topic not in self.retained and time.time() < deadline:
                self.cv.wait(0.2)
            return self.retained.get(topic)

    def close(self):
        self.cl.loop_stop()
        self.cl.disconnect()


def report(ack, what):
    if ack is None:
        print(f"{what}: no answer from the gateway")
        return 3
    print(f"{what}: {'ok' if ack['ok'] else 'REFUSED'} - {ack.get('detail', '')}")
    return 0 if ack["ok"] else 2


def cmd_validate(args):
    prof = mp.load_profile(args.file)
    issues = mp.validate(prof)
    for i in issues:
        print(f"{i['level']:5} {i['path'] or '-':28} {i['code']}: {i['msg']}")
    errors = [i for i in issues if i["level"] == "error"]
    if errors:
        print(f"{len(errors)} error(s)")
        return 1
    timing, regs = mp.resolve(prof)
    blocks = mp.plan_blocks(regs, timing["max_block"])
    print(f"ok: {prof['id']} rev {prof.get('rev', 1)}, {len(regs)} registers, "
          f"{len(blocks)} request(s) per sweep, {len(mp.canonical_json(prof))} bytes of metadata")
    return 0


def cmd_push(args, link):
    prof = mp.load_profile(args.file)
    errors = [i for i in mp.validate(prof) if i["level"] == "error"]
    if errors:
        for i in errors:
            print(f"error {i['path']}: {i['code']}: {i['msg']}")
        return 1
    cmds = mp.wire_commands(prof)
    for n, (action, cargs) in enumerate(cmds, 1):
        rc = report(link.send(action, cargs), f"[{n}/{len(cmds)}] {action}")
        if rc:
            return rc
    if args.assign:
        return report(link.send("profile_assign", {"analyzer": args.assign, "profile": prof["id"]}),
                      f"assign {args.assign}")
    return 0


def cmd_list(args, link):
    body = link.profiles()
    if body is None:
        print("no profiles topic yet (gateway offline, or firmware without profile support)")
        return 3
    for it in body["profiles"]:
        print(f"{it['id']:24} rev {it['rev']:<5} {it['n']:>2} regs  {it.get('name', '')}"
              + ("  (built in)" if it.get("builtin") else ""))
    for aid, pid in body["assign"].items():
        print(f"  {aid} reads as {pid}")
    cap = body.get("cap", {})
    print(f"limits: {cap.get('regs')} registers/profile, {cap.get('profiles')} stored, "
          f"{cap.get('free')} bytes free")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("file")
    for name in ("push", "list", "assign", "test", "delete"):
        sp = sub.add_parser(name)
        sp.add_argument("--modem", default="gw-01")
        sp.add_argument("--host", default="broker.emqx.io")
        sp.add_argument("--port", type=int, default=0)
        sp.add_argument("--tls", action="store_true")
        sp.add_argument("--user", default="")
        sp.add_argument("--pass", dest="password", default="")
        sp.add_argument("--timeout", type=float, default=10.0)
        if name == "push":
            sp.add_argument("file")
            sp.add_argument("--assign", metavar="ANALYZER")
        if name in ("assign", "test"):
            sp.add_argument("--analyzer", required=True)
        if name in ("assign", "delete"):
            sp.add_argument("--profile", required=True)
        if name == "test":
            sp.add_argument("--address", type=int, required=True)
            sp.add_argument("--fc", type=int, default=3)
            sp.add_argument("--type", default="f32")
            sp.add_argument("--word-order", default="big")
            sp.add_argument("--byte-order", default="big")
            sp.add_argument("--scale", type=float, default=1)
            sp.add_argument("--offset", type=float, default=0)
            sp.add_argument("--count", type=int, default=0, help="raw dump of N registers, no decoding")
    args = ap.parse_args()

    if args.cmd == "validate":
        return cmd_validate(args)

    link = Link(args)
    try:
        if args.cmd == "push":
            return cmd_push(args, link)
        if args.cmd == "list":
            return cmd_list(args, link)
        if args.cmd == "assign":
            return report(link.send("profile_assign", {"analyzer": args.analyzer, "profile": args.profile}), "assign")
        if args.cmd == "delete":
            return report(link.send("profile_delete", {"id": args.profile}), "delete")
        if args.cmd == "test":
            a = {"analyzer": args.analyzer, "address": args.address, "fc": args.fc}
            if args.count:
                a["count"] = args.count
            else:
                a.update(type=args.type, word_order=args.word_order, byte_order=args.byte_order,
                         scale=args.scale, offset=args.offset)
            return report(link.send("profile_test", a), "test")
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
