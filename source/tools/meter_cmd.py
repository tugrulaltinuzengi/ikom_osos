#!/usr/bin/env python3
"""CLI: publish one command to a modem and print the ack.

    python meter_cmd.py --modem gw-01 ping
    python meter_cmd.py --modem gw-01 read_now --analyzer an-01
    python meter_cmd.py --modem gw-01 set_interval --seconds 2
    python meter_cmd.py --modem gw-01 sleep --on
    python meter_cmd.py --modem gw-01 load --ch 3 --on

Against the real gateway on EMQX Serverless, add TLS and credentials:

    python meter_cmd.py --tls --host nba17802.ala.eu-central-1.emqxsl.com \\
        --user headend --pass ... --modem gw-01 ping

Exit codes: 0 ack ok, 2 ack refused, 3 no ack. Scriptable on purpose - the
firmware bench verification in the plan drives this.
"""
import argparse
import json
import ssl
import sys
import time

import paho.mqtt.client as mqtt

import osos_proto as p

ACTIONS = ["ping", "read_now", "set_interval", "sleep", "load"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=ACTIONS)
    ap.add_argument("--modem", default="gw-01")
    ap.add_argument("--analyzer", default=None, help="for read_now")
    ap.add_argument("--seconds", type=int, help="for set_interval")
    ap.add_argument("--ch", type=int, default=None, help="for load, 1-based")
    ap.add_argument("--on", dest="on", action="store_true")
    ap.add_argument("--off", dest="on", action="store_false")
    ap.set_defaults(on=None)
    ap.add_argument("--host", default="broker.emqx.io")
    ap.add_argument("--port", type=int, default=0, help="default 1883, or 8883 with --tls")
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--user", default="")
    ap.add_argument("--pass", dest="password", default="")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    cargs = {}
    if args.action == "set_interval":
        if not args.seconds:
            sys.exit("set_interval needs --seconds")
        cargs["seconds"] = args.seconds
    if args.action == "sleep" and args.on is None:
        sys.exit("sleep needs --on or --off")
    if args.action == "load":
        if args.ch is None:
            sys.exit("load needs --ch")
        if args.on is None:
            sys.exit("load needs --on or --off")
    if args.analyzer:
        cargs["analyzer"] = args.analyzer
    if args.ch is not None:
        cargs["ch"] = args.ch
    if args.on is not None:
        cargs["on"] = args.on

    # Topics come from the shared grammar, never from f-strings here: three
    # implementations have to agree on them (osos_proto.py, TopicRouter.kt,
    # commands.h) and a typo in a CLI is the cheapest place to hide a mismatch.
    cmd_topic = p.modem_topic(args.modem, "cmd")
    ack_topic = p.modem_topic(args.modem, "ack")

    cid = f"cli-{int(time.time())}"
    done = {}

    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"meter-cli-{cid}")
    if args.user:
        cl.username_pw_set(args.user, args.password)
    port = args.port or (8883 if args.tls else 1883)
    if args.tls:
        cl.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    def on_connect(cl, *_):
        cl.subscribe(ack_topic, qos=1)
        cl.publish(cmd_topic, json.dumps(
            {"v": p.PROTO_V, "id": cid, "action": args.action, "args": cargs}), qos=1)
        print(f"-> {cmd_topic}  {args.action} {cargs or ''}  as {cid}")

    def on_message(cl, _u, m):
        try:
            ack = json.loads(m.payload)
        except ValueError:
            return
        # Match on the command id: another client's ack on the same topic is
        # not an answer to this command.
        if ack.get("id") == cid:
            done["ack"] = ack

    cl.on_connect = on_connect
    cl.on_message = on_message
    cl.connect(args.host, port, keepalive=15)
    cl.loop_start()
    t0 = time.time()
    while "ack" not in done and time.time() - t0 < args.timeout:
        time.sleep(0.1)
    cl.loop_stop()
    if "ack" in done:
        a = done["ack"]
        elapsed = time.time() - t0
        print(f"ack: ok={a.get('ok')} detail={a.get('detail')!r}  ({elapsed:.1f}s)")
        sys.exit(0 if a.get("ok") else 2)
    print(f"NO ACK after {args.timeout}s (modem {args.modem} offline?)")
    sys.exit(3)


if __name__ == "__main__":
    main()
