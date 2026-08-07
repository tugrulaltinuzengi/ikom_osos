#!/usr/bin/env python3
"""PC stand-in for the ESP32-S3 gateway. Speaks the exact SRS-01 protocol the
firmware implements, with simulated DKM-440 values. Use it to develop/test the
phone page and MQTT Dash without any hardware.

    python fake_gateway.py [--gw dkm440-gw1-test] [--host broker.emqx.io]
                           [--port 1883] [--interval 10]
"""
import argparse
import json
import math
import random
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# Every key from modbus/dkm_440_analyze/map.py MODBUS_MAP.
def sim_values(t):
    wob = lambda base, amp: round(base + amp * math.sin(t / 30) + random.uniform(-amp / 3, amp / 3), 2)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gw", default="dkm440-gw1-test")
    ap.add_argument("--host", default="broker.emqx.io")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--user", default="")
    ap.add_argument("--pass", dest="password", default="")
    args = ap.parse_args()

    base = f"osos/{args.gw}"
    state = {"interval": args.interval, "seq": 0, "wake": threading.Event()}

    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{args.gw}-fake")
    if args.user:
        cl.username_pw_set(args.user, args.password)
    cl.will_set(f"{base}/status", json.dumps({"state": "offline"}), qos=1, retain=True)

    def publish_telemetry():
        state["seq"] += 1
        msg = {"ts": now_iso(), "seq": state["seq"], "buffered": False,
               "values": sim_values(time.time()), "meter_ok": True}
        cl.publish(f"{base}/telemetry", json.dumps(msg), qos=1)
        print(f"telemetry seq={state['seq']}")

    def on_connect(cl, _u, _f, rc, _p=None):
        print(f"connected rc={rc}; publishing as {base}/*")
        cl.publish(f"{base}/status",
                   json.dumps({"state": "online", "fw": "fake-pc-0.1", "bearer": "pc",
                               "ip": "127.0.0.1", "rssi": 0}), qos=1, retain=True)
        cl.subscribe(f"{base}/cmd", qos=1)

    def on_message(cl, _u, m):
        try:
            cmd = json.loads(m.payload)
        except ValueError:
            return
        cid, action, cargs = cmd.get("id", "?"), cmd.get("action"), cmd.get("args", {})
        print(f"cmd {cid}: {action} {cargs}")
        ok, detail = True, ""
        if action == "read_now":
            publish_telemetry()
            detail = f"published seq {state['seq']}"
        elif action == "set_interval":
            s = int(cargs.get("seconds", 0))
            if 1 <= s <= 900:
                state["interval"] = s
                state["wake"].set()
                detail = f"interval={s}s"
            else:
                ok, detail = False, "seconds out of range 1..900"
        elif action == "ping":
            detail = f"alive, interval={state['interval']}s, seq={state['seq']}"
        else:
            ok, detail = False, f"'{action}' not supported in phase 1"
        cl.publish(f"{base}/ack", json.dumps({"id": cid, "ok": ok, "detail": detail}), qos=1)

    cl.on_connect = on_connect
    cl.on_message = on_message
    cl.connect(args.host, args.port, keepalive=30)
    cl.loop_start()
    try:
        while True:
            publish_telemetry()
            state["wake"].wait(state["interval"])
            state["wake"].clear()
    except KeyboardInterrupt:
        pass
    finally:
        cl.publish(f"{base}/status", json.dumps({"state": "offline"}), qos=1, retain=True)
        cl.loop_stop()


if __name__ == "__main__":
    main()
