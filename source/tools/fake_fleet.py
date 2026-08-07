#!/usr/bin/env python3
"""PC stand-in for a fleet of OSOS modems. Speaks protocol v2 in full, so it is
the reference implementation the app is developed against and the thing that
demonstrates 25 analyzers per modem - a scale the ESP8266 build is capped below
(see the spec, D-7).

    python fake_fleet.py --modems 3 --analyzers 25 --host broker.emqx.io
"""
import argparse
import json
import math
import random
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

import osos_proto as p

LOAD_CHANNELS = 4
SLEEP_INTERVAL_S = 300


def sim_values(t, drift):
    def wob(base, amp):
        return round(base + amp * math.sin(t / 30 + drift)
                     + random.uniform(-amp / 3, amp / 3), 2)

    v = {}
    for ph, off in (("L1", 0), ("L2", -1.5), ("L3", 1.1)):
        v[f"MainBus_Voltage_{ph}"] = wob(230 + off, 1.5)
        v[f"MainBus_Current_{ph}"] = wob(4.2 + off / 10, 0.4)
        v[f"MainBus_Freq_{ph}"] = wob(50.0, 0.02)
        v[f"MainBus_PF_{ph}"] = wob(0.92, 0.02)
        v[f"MainBus_CosPhi_{ph}"] = wob(0.93, 0.02)
        v[f"MainBus_TanPhi_{ph}"] = wob(0.40, 0.03)
    v["MainBus_Voltage_N"] = wob(0.6, 0.2)
    v["MainBus_Current_N"] = wob(0.3, 0.1)
    v["MainBus_TanPhi_Tot"] = wob(0.40, 0.02)
    v["Supply_Voltage"] = wob(229.0, 1.0)
    return v


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Modem:
    def __init__(self, mid, n_analyzers, interval):
        self.mid = mid
        self.awake_interval = interval
        self.interval = interval
        self.sleep = False
        self.loads = [False] * LOAD_CHANNELS
        self.since = now_iso()
        self.seq = 0
        self.analyzers = [
            {"id": f"an-{i + 1:02d}", "host": f"192.169.10.{100 + i}",
             "port": 502, "unit": 1, "interval": interval}
            for i in range(n_analyzers)
        ]

    def status_payload(self):
        return {"v": p.PROTO_V, "state": "online", "fw": "fake-fleet-0.1",
                "bearer": "pc", "ip": "127.0.0.1", "rssi": -46,
                "heap": 28944, "analyzers": len(self.analyzers)}

    def registry_payload(self):
        return {"v": p.PROTO_V, "rev": 1,
                "loads": {"channels": LOAD_CHANNELS},
                "analyzers": self.analyzers}

    def state_payload(self):
        return {"v": p.PROTO_V, "sleep": self.sleep,
                "interval": self.interval, "loads": self.loads,
                "since": self.since}


class Fleet:
    def __init__(self, args):
        self.args = args
        self.modems = {
            f"gw-{i + 1:02d}": Modem(f"gw-{i + 1:02d}", args.analyzers,
                                     args.interval)
            for i in range(args.modems)
        }
        self.wake = threading.Event()
        self.connected = threading.Event()
        self.next_due = {}
        self.drops = {}
        self.link_state = {}
        self.cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"fake-fleet-{random.randint(0, 9999)}")
        # A fleet publishes far more than paho's default 20-message inflight
        # window allows at QoS 1. Left at the default, a 3x8 fleet starves its
        # own later modems and the retained status/registry from on_connect
        # queue behind the telemetry burst and never land.
        self.cl.max_inflight_messages_set(200)
        if args.user:
            self.cl.username_pw_set(args.user, args.password)
        # One LWT per client, so it covers the first modem; the rest are
        # marked offline by the finally block in run(). A real modem is one
        # client and gets its own.
        first = next(iter(self.modems))
        self.cl.will_set(p.modem_topic(first, "status"),
                         json.dumps({"v": p.PROTO_V, "state": "offline"}),
                         qos=1, retain=True)
        self.cl.on_connect = self.on_connect
        self.cl.on_message = self.on_message

    def pub(self, topic, payload, retain=False):
        # Never publish blind. A silently dropped publish looks identical to a
        # dead modem from the app's side, and at fleet scale the drops land on
        # whichever modems happen to be published last.
        info = self.cl.publish(topic, json.dumps(payload), qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.drops[info.rc] = self.drops.get(info.rc, 0) + 1
        return info

    def on_connect(self, cl, _u, _f, rc, _p=None):
        print(f"connected rc={rc}; {len(self.modems)} modems x "
              f"{self.args.analyzers} analyzers")
        for m in self.modems.values():
            self.pub(p.modem_topic(m.mid, "status"), m.status_payload(), True)
            self.pub(p.modem_topic(m.mid, "registry"), m.registry_payload(), True)
            self.pub(p.modem_topic(m.mid, "state"), m.state_payload(), True)
            cl.subscribe(p.modem_topic(m.mid, "cmd"), qos=1)
        self.connected.set()

    def on_message(self, cl, _u, msg):
        kind, mid, _aid, leaf = p.parse(msg.topic)
        if kind != "modem" or leaf != "cmd":
            return
        m = self.modems.get(mid)
        if m is None:
            return
        try:
            cmd = json.loads(msg.payload)
        except ValueError:
            return

        cid = cmd.get("id", "?")
        action = cmd.get("action")
        args = cmd.get("args", {}) or {}
        ok, detail = self.dispatch(m, action, args)
        print(f"{mid} cmd {cid}: {action} {args} -> {ok} {detail}")
        self.pub(p.modem_topic(mid, "ack"),
                 {"v": p.PROTO_V, "id": cid, "ok": ok, "detail": detail})

    def dispatch(self, m, action, args):
        if action == "ping":
            return True, f"alive, interval={m.interval}s, seq={m.seq}"

        if action == "read_now":
            aid = args.get("analyzer")
            targets = ([a for a in m.analyzers if a["id"] == aid] if aid
                       else m.analyzers)
            if not targets:
                return False, f"no such analyzer: {aid}"
            for a in targets:
                self.publish_analyzer(m, a)
            return True, f"published {len(targets)} analyzer(s)"

        if action == "set_interval":
            s = int(args.get("seconds", 0))
            if not 1 <= s <= 900:
                return False, "seconds out of range 1..900"
            m.awake_interval = s
            if not m.sleep:
                m.interval = s
                self.wake.set()
            self.pub(p.modem_topic(m.mid, "state"), m.state_payload(), True)
            return True, f"interval={s}s"

        if action == "sleep":
            on = bool(args.get("on"))
            m.sleep = on
            m.interval = SLEEP_INTERVAL_S if on else m.awake_interval
            m.since = now_iso()
            self.wake.set()
            self.pub(p.modem_topic(m.mid, "state"), m.state_payload(), True)
            self.pub(p.modem_topic(m.mid, "event"),
                     {"v": p.PROTO_V, "ts": now_iso(),
                      "type": "sleep_enter" if on else "sleep_exit"})
            return True, f"sleep {'on' if on else 'off'}, interval {m.interval}s"

        if action == "load":
            ch = args.get("ch")
            if not isinstance(ch, int) or not 1 <= ch <= LOAD_CHANNELS:
                return False, f"ch out of range 1..{LOAD_CHANNELS}"
            on = bool(args.get("on"))
            m.loads[ch - 1] = on
            # State reports what is observed, never what was requested.
            self.pub(p.modem_topic(m.mid, "state"), m.state_payload(), True)
            self.pub(p.modem_topic(m.mid, "event"),
                     {"v": p.PROTO_V, "ts": now_iso(), "type": "load_switch",
                      "ch": ch, "on": on})
            return True, f"ch{ch} {'on' if on else 'off'}"

        return False, f"unknown action: {action}"

    def publish_analyzer(self, m, a):
        m.seq += 1
        drift = hash(a["id"]) % 100 / 10.0
        self.pub(
            p.analyzer_topic(m.mid, a["id"], "telemetry"),
            {"v": p.PROTO_V, "ts": now_iso(), "seq": m.seq, "buffered": False,
             "meter_ok": True, "values": sim_values(time.time(), drift)},
        )
        # Analyzer status is retained and only changes on a link transition.
        # Republishing it every cycle doubled the fleet's message rate for no
        # new information - which matters, because a free public broker will
        # silently throttle a fleet long before it refuses a publish.
        key = (m.mid, a["id"])
        if self.link_state.get(key) != "online":
            self.link_state[key] = "online"
            self.pub(
                p.analyzer_topic(m.mid, a["id"], "status"),
                {"v": p.PROTO_V, "state": "online", "host": a["host"],
                 "unit": a["unit"], "last_ok": now_iso(), "fail_streak": 0},
                True,
            )

    def run(self):
        self.cl.connect(self.args.host, self.args.port, keepalive=30)
        self.cl.loop_start()
        # Do not publish a single frame before CONNACK. Telemetry issued into
        # the pre-connection queue arrived ahead of on_connect's retained
        # registry/state and cost them - the app then saw analyzers with no
        # host, no interval and no load channels, so the whole load-control UI
        # was missing. Waiting is free; a lost retained topic is not.
        if not self.connected.wait(20):
            print("WARNING: no CONNACK after 20s - publishing anyway")
        last_status = 0.0
        try:
            while True:
                now = time.time()

                # Per-analyzer due times rather than one burst per cycle. The
                # burst version published every analyzer of every modem back to
                # back, which starved the later modems and delayed retained
                # messages behind a long QoS-1 queue. This mirrors the firmware's
                # round-robin scheduler in fleet.h.
                published = 0
                for m in self.modems.values():
                    for a in m.analyzers:
                        key = (m.mid, a["id"])
                        if now >= self.next_due.get(key, 0.0):
                            self.publish_analyzer(m, a)
                            self.next_due[key] = now + m.interval
                            published += 1

                # All three retained topics are republished periodically, so a
                # stale "offline" left by an ungraceful exit - or a retained
                # message lost to a connection race - heals itself instead of
                # making a live fleet look dead or unconfigured.
                if now - last_status >= 30:
                    last_status = now
                    for m in self.modems.values():
                        self.pub(p.modem_topic(m.mid, "status"),
                                 m.status_payload(), True)
                        self.pub(p.modem_topic(m.mid, "registry"),
                                 m.registry_payload(), True)
                        self.pub(p.modem_topic(m.mid, "state"),
                                 m.state_payload(), True)

                if published:
                    drops = (" DROPPED " + str(self.drops)) if self.drops else ""
                    print(f"published {published} analyzer frames "
                          f"({len(self.modems)} modems, "
                          f"{sum(1 for m in self.modems.values() if m.sleep)} asleep)"
                          f"{drops}")
                    self.drops = {}

                self.wake.wait(0.25)
                self.wake.clear()
        except KeyboardInterrupt:
            pass
        finally:
            for m in self.modems.values():
                self.pub(p.modem_topic(m.mid, "status"),
                         {"v": p.PROTO_V, "state": "offline"}, True)
            self.cl.loop_stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modems", type=int, default=3)
    ap.add_argument("--analyzers", type=int, default=25)
    ap.add_argument("--host", default="broker.emqx.io")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--user", default="")
    ap.add_argument("--pass", dest="password", default="")
    Fleet(ap.parse_args()).run()


if __name__ == "__main__":
    main()
