#!/usr/bin/env python3
"""Record an OSOS soak run to a JSONL file for later analysis.

The phone app cannot be the system of record for a soak. `TelemetryHistory` is
capped at 720 frames and lives only in RAM (data/TelemetryHistory.kt), which is
one hour at the 5 s report interval - and Android will happily kill the app
overnight, taking the lot with it. This recorder runs on the bench PC instead:
it is independent of the phone, appends every message to disk as it arrives, and
survives broker outages.

    python soak_recorder.py --host your-deployment.emqxsl.com --port 8883 \
        --tls --user USER --pass PASS --gw dkm440-gw1 --out soak-2026-08-01.jsonl

Credentials are read from the environment when the flags are omitted:
OSOS_MQTT_HOST, OSOS_MQTT_PORT, OSOS_MQTT_USER, OSOS_MQTT_PASS, OSOS_GW.
Nothing is ever written to the log except message payloads - no credentials.

Analyse the result with soak_report.py.
"""
import argparse
import json
import os
import ssl
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# Subscribe at QoS 1 so the broker redelivers to *us* on a flaky PC link. Note
# this cannot recover what the gateway never sent: the ESP8266 publishes with
# PubSubClient, which is QoS 0 only, and drops frames outright while the broker
# is unreachable (osos_gw8266.ino - "broker down - reading anyway, frame
# dropped"). Loss measured here is therefore real end-to-end loss.
SUB_QOS = 1
SUBTOPICS = ("telemetry", "status", "ack", "event")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Recorder:
    def __init__(self, path, gw):
        self.fh = open(path, "a", encoding="utf-8")
        self.base = f"osos/{gw}"
        self.count = 0
        self.started = time.time()

    def write(self, obj):
        """One JSON object per line, flushed immediately.

        Flushing every line costs nothing at a 5 s cadence and means a power cut
        or a Ctrl-C loses at most the record in flight. A soak log that is itself
        unreliable proves nothing.
        """
        obj["rx"] = time.time()
        obj["rx_iso"] = now_iso()
        self.fh.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self.fh.flush()
        os.fsync(self.fh.fileno())

    def note(self, event, **kw):
        """Record a recorder-side lifecycle event.

        These are tagged `_recorder` so the analyser can tell "the gateway went
        quiet" apart from "the PC lost its own connection" - without them a
        recorder dropout is indistinguishable from a gateway failure.
        """
        self.write({"topic": "_recorder", "event": event, **kw})
        print(f"[{now_iso()}] recorder: {event} {kw or ''}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("OSOS_MQTT_HOST", "broker.emqx.io"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("OSOS_MQTT_PORT", "1883")))
    ap.add_argument("--tls", action="store_true", default=bool(os.environ.get("OSOS_MQTT_TLS")))
    ap.add_argument("--user", default=os.environ.get("OSOS_MQTT_USER", ""))
    ap.add_argument("--pass", dest="password", default=os.environ.get("OSOS_MQTT_PASS", ""))
    ap.add_argument("--gw", default=os.environ.get("OSOS_GW", "dkm440-gw1"))
    ap.add_argument("--out", default=None, help="JSONL output path (default soak-<date>.jsonl)")
    args = ap.parse_args()

    out = args.out or f"soak-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    rec = Recorder(out, args.gw)

    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                     client_id=f"soak-{int(time.time())}")
    if args.user:
        cl.username_pw_set(args.user, args.password)
    if args.tls:
        # emqxsl.com presents a public DigiCert chain, so the system trust store
        # is enough - no custom CA bundle to keep in sync.
        cl.tls_set_context(ssl.create_default_context())

    def on_connect(_c, _u, _f, rc, _p=None):
        rec.note("connected", rc=str(rc))
        for t in SUBTOPICS:
            cl.subscribe(f"{rec.base}/{t}", qos=SUB_QOS)

    def on_disconnect(_c, _u, _f, rc, _p=None):
        rec.note("disconnected", rc=str(rc))

    def on_message(_c, _u, m):
        try:
            payload = json.loads(m.payload)
        except ValueError:
            payload = m.payload.decode("utf-8", "replace")
        rec.count += 1
        rec.write({"topic": m.topic, "payload": payload, "retain": bool(m.retain)})
        if m.topic.endswith("/telemetry") and isinstance(payload, dict):
            vals = payload.get("values", {})
            ok = sum(1 for v in vals.values() if v is not None)
            print(f"[{now_iso()}] seq={payload.get('seq')} {ok}/{len(vals)} regs "
                  f"meter_ok={payload.get('meter_ok')} n={rec.count}", flush=True)

    cl.on_connect, cl.on_disconnect, cl.on_message = on_connect, on_disconnect, on_message

    # Reconnect forever: an overnight run must not end because the PC's wifi
    # blinked at 03:00.
    cl.reconnect_delay_set(min_delay=1, max_delay=30)
    rec.note("start", host=args.host, port=args.port, tls=args.tls, gw=args.gw, out=out)
    cl.connect(args.host, args.port, keepalive=30)

    try:
        cl.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        pass
    finally:
        rec.note("stop", messages=rec.count,
                 duration_s=round(time.time() - rec.started, 1))
        cl.loop_stop()
        rec.fh.close()
        print(f"\nwrote {rec.count} messages to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
