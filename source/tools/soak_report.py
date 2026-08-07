#!/usr/bin/env python3
"""Turn a soak_recorder.py JSONL log into the reliability numbers.

    python soak_report.py soak-20260801-210000.jsonl [--md report.md]

Every metric here is computed from the message *envelope* (seq, ts, meter_ok,
null-count) rather than from the measured values. That is deliberate: it is what
makes the soak meaningful on a bench where the AC inputs are not energised and
every ANA BARA register reads 0.00.

The one value-derived metric is the staleness check, which asks whether a key
ever changed. On the supply-only bench `Supply_Voltage` is the only channel that
can move, so it is the sole canary for "the pipeline is live" as opposed to "the
pipeline is replaying a frozen frame".
"""
import argparse
import json
import statistics
from collections import defaultdict

# The gateway's seq is monotonic *per boot* (osos_gw8266.ino:44,129), so a drop
# in seq means the ESP8266 restarted. Delivery ratio must be computed per boot
# segment - treating the whole run as one sequence would report a huge phantom
# loss at every reboot.
def segment_by_boot(frames):
    segments, cur = [], []
    for f in frames:
        if cur and f["seq"] <= cur[-1]["seq"]:
            segments.append(cur)
            cur = []
        cur.append(f)
    if cur:
        segments.append(cur)
    return segments


def fmt_dur(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--md", default=None, help="also write a markdown report here")
    args = ap.parse_args()

    frames, recorder_events, statuses = [], [], []
    with open(args.log, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            topic = rec.get("topic", "")
            if topic == "_recorder":
                recorder_events.append(rec)
            elif topic.endswith("/telemetry"):
                p = rec.get("payload")
                if isinstance(p, dict) and isinstance(p.get("seq"), int):
                    frames.append({"rx": rec["rx"], "seq": p["seq"],
                                   "meter_ok": p.get("meter_ok"),
                                   "buffered": p.get("buffered"),
                                   "values": p.get("values", {})})
            elif topic.endswith("/status"):
                statuses.append(rec)

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    if not frames:
        emit("No telemetry frames in the log. Nothing to report.")
        return

    span = frames[-1]["rx"] - frames[0]["rx"]
    segments = segment_by_boot(frames)

    expected = sum(s[-1]["seq"] - s[0]["seq"] + 1 for s in segments)
    received = len(frames)
    missing = expected - received

    # Gaps, per segment so a reboot is not counted as a gap.
    gaps = []
    for seg in segments:
        for a, b in zip(seg, seg[1:]):
            if b["seq"] - a["seq"] > 1:
                gaps.append(b["seq"] - a["seq"] - 1)

    deltas = [b["rx"] - a["rx"] for a, b in zip(frames, frames[1:])]

    disconnects = [e for e in recorder_events if e.get("event") == "disconnected"]

    faults, fault_run = [], 0
    for f in frames:
        if f["meter_ok"] is False:
            fault_run += 1
        elif fault_run:
            faults.append(fault_run)
            fault_run = 0
    if fault_run:
        faults.append(fault_run)

    reg_counts = [sum(1 for v in f["values"].values() if v is not None) for f in frames]
    total_keys = max((len(f["values"]) for f in frames), default=0)

    emit("=" * 62)
    emit("OSOS SOAK REPORT")
    emit("=" * 62)
    emit(f"log                  {args.log}")
    emit(f"wall clock           {fmt_dur(span)}")
    emit(f"gateway boots        {len(segments)}"
         + ("  (seq reset detected)" if len(segments) > 1 else ""))
    emit("")
    emit("--- delivery -------------------------------------------------")
    emit(f"frames received      {received}")
    emit(f"frames expected      {expected}   (from seq range, per boot)")
    emit(f"frames missing       {missing}")
    emit(f"delivery ratio       {100.0 * received / expected:.3f} %" if expected else "n/a")
    emit(f"gap events           {len(gaps)}"
         + (f"   largest {max(gaps)} frames" if gaps else ""))
    emit(f"recorder dropouts    {len(disconnects)}   (PC-side, not gateway fault)")
    emit("")
    emit("--- cadence --------------------------------------------------")
    if deltas:
        emit(f"interval median      {statistics.median(deltas):.2f} s")
        emit(f"interval min / max   {min(deltas):.2f} s / {max(deltas):.2f} s")
        stalls = [d for d in deltas if d > 3 * statistics.median(deltas)]
        emit(f"stalls (>3x median)  {len(stalls)}"
             + (f"   longest {max(stalls):.1f} s" if stalls else ""))
    emit("")
    emit("--- meter link -----------------------------------------------")
    emit(f"meter fault episodes {len(faults)}")
    if faults:
        emit(f"longest fault run    {max(faults)} frames")
    if reg_counts:
        full = sum(1 for c in reg_counts if c == total_keys)
        emit(f"full register reads  {full}/{len(reg_counts)} "
             f"({100.0 * full / len(reg_counts):.2f} %)  [{total_keys}/{total_keys} regs]")
        if min(reg_counts) < total_keys:
            emit(f"worst cycle          {min(reg_counts)}/{total_keys} registers")
    buffered = sum(1 for f in frames if f.get("buffered"))
    emit(f"buffered frames      {buffered}   "
         "(fw 0.3.0 hardcodes false - no store-and-forward)")
    emit("")
    emit("--- channels -------------------------------------------------")
    series = defaultdict(list)
    for f in frames:
        for k, v in f["values"].items():
            if v is not None:
                series[k].append(float(v))
    emit(f"{'key':<24}{'min':>10}{'max':>10}{'mean':>10}  moved?")
    for k in sorted(series):
        vals = series[k]
        moved = "yes" if (max(vals) - min(vals)) > 1e-9 else "NO - frozen/zero"
        emit(f"{k:<24}{min(vals):>10.3f}{max(vals):>10.3f}"
             f"{statistics.fmean(vals):>10.3f}  {moved}")
    emit("")
    live = [k for k in series if (max(series[k]) - min(series[k])) > 1e-9]
    if live:
        emit(f"staleness canary     OK - {len(live)} channel(s) moved: {', '.join(live)}")
    else:
        emit("staleness canary     ** NONE ** - every channel constant for the whole run.")
        emit("                     A frozen pipeline would look identical to this.")
        emit("                     Nudge the bench PSU during the next soak.")
    emit("=" * 62)

    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write("# OSOS soak report\n\n```\n" + "\n".join(out) + "\n```\n")
        print(f"\nmarkdown written to {args.md}")


if __name__ == "__main__":
    main()
