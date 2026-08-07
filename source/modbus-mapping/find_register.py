"""Reverse-engineer the DKM-440 register map by INJECTING A KNOWN STIMULUS.

You feed a known voltage into one input (e.g. L1) with your bench supply, read
the multimeter, and this tool finds which Modbus register moved with it - giving
you both the ADDRESS and the SCALE (raw / engineering value) at once.

Four modes (run `python find_register.py <mode> -h` for each):

  probe                       quick sanity read of the voltage block (comms test)
  scan   --start A --count N  dump a window once, every plausible interpretation
  watch  --start A --count N  live: shows which registers move as you turn the knob
  calibrate --label L1 ...    the rigorous one: enter several known voltages, get a
                              linear fit per register -> the best fit IS your register

--------------------------------------------------------------------------------
THE METHOD IN ONE PARAGRAPH
--------------------------------------------------------------------------------
A measurement register holds  raw = scale * value.  If you apply a series of known
voltages V and record the raw register at each, the true L1 register plots a
straight line raw = scale*V (slope = scale, intercept ~ 0, R^2 ~ 1.000). Every
other register is either constant (no fit) or noise (bad fit). So the register
with the cleanest straight-line fit against your applied voltages is the answer,
and its slope tells you the scale (10 => the reading is raw/10 volts, etc.).

Serial port / framing live in dkm_modbus.py (COM13, 19200 8N1, slave 1).
CLOSE QModMaster before running - the COM port is exclusive.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time

import dkm_modbus
from dkm_modbus import DKM, as_signed16, combine32, nearest_nice_scale

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# Default window: the measurement block base is 0x5000 = 20480 on this 440, 16-bit,
# with the phase voltages confirmed at 20480/20481/20482 (/10 => volts). We scan a
# few hundred registers from there so currents/powers/averages are in view too.
DEF_START = 20480
DEF_COUNT = 256


# ===========================================================================
# helpers
# ===========================================================================
def _ensure_results():
    os.makedirs(RESULTS_DIR, exist_ok=True)


def _fmt_interps(v):
    """Every plausible reading of one 16-bit register, as a dict of strings."""
    return {
        "dec": v,
        "hex": f"0x{v:04X}",
        "/10": f"{v / 10.0:.1f}",
        "/100": f"{v / 100.0:.2f}",
        "/1000": f"{v / 1000.0:.3f}",
        "s16": as_signed16(v),
    }


def _linfit(xs, ys):
    """Ordinary least squares y = m*x + b. Returns (m, b, r2). r2 is None if x or y
    is constant (no line can be fitted / no variation to explain)."""
    n = len(xs)
    if n < 2:
        return None
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    sxx = sum((x - xbar) ** 2 for x in xs)
    syy = sum((y - ybar) ** 2 for y in ys)
    sxy = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None
    m = sxy / sxx
    b = ybar - m * xbar
    ss_res = sum((y - (m * x + b)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / syy
    return m, b, r2


def timed_scan(dev,
               start=0,
               count=25000,
               duration=60,
               chunk=100,
               outfile="timed_scan.csv"):

    end_time = time.time() + duration

    print(f"Scanning registers {start}..{start+count-1}")
    print(f"Duration : {duration} seconds")
    print(f"Saving to : {outfile}")

    with open(outfile, "w", newline="") as f:

        writer = csv.writer(f)
        writer.writerow(["time", "address", "value"])

        scan = 0

        while time.time() < end_time:

            t = time.time()

            vals = dev.read_window(
                start,
                count,
                chunk=chunk,
                recover=True
            )

            for addr, value in vals.items():
                writer.writerow([t, addr, value])

            scan += 1

            print(
                f"Scan {scan:3d} : {len(vals)} registers",
                end="\r"
            )

    print("\nFinished.")

# ===========================================================================
# probe - comms sanity check
# ===========================================================================
def cmd_probe(dev, args):
    print(f"Reading voltage block {DEF_START}..{DEF_START + 7} on {dev.port} ...")
    vals = dev.read(DEF_START, 8)
    labels = ["L1", "L2", "L3", "L12", "L23", "L31", "?", "?"]
    print(f"\n  addr    raw     /10 (V)   label")
    print(f"  -----   -----   -------   -----")
    for i, v in enumerate(vals):
        print(f"  {DEF_START + i:>5}   {v:>5}   {v / 10.0:>7.1f}   {labels[i]}")
    live = [v for v in vals[:6] if v > 50]
    if live:
        print(f"\nOK - comms good. Phase voltages ~{sum(live) / len(live) / 10.0:.0f} V. "
              f"You're talking to the meter.")
    else:
        print("\nComms good but the voltage inputs read ~0 - no AC on the terminals yet, "
              "or the source is off. That's expected before you wire the supply to L1/N.")


# ===========================================================================
# scan - one-shot interpretation dump
# ===========================================================================
def cmd_scan(dev, args):
    win = dev.read_window(args.start, args.count)
    if not win:
        sys.exit("No registers answered in that window. Try a smaller --count near 20480.")
    print(f"Window {args.start}..{args.start + args.count - 1}  "
          f"({len(win)} registers answered)\n")
    print(f"  {'addr':>6} {'hex':>7} {'dec':>7} {'/10':>9} {'/100':>9} "
          f"{'/1000':>9} {'s16':>8}")
    print("  " + "-" * 62)
    for addr in sorted(win):
        it = _fmt_interps(win[addr])
        print(f"  {addr:>6} {it['hex']:>7} {it['dec']:>7} {it['/10']:>9} "
              f"{it['/100']:>9} {it['/1000']:>9} {it['s16']:>8}")
    print("\nTip: three near-equal /10 values in a row = the three phase voltages.\n"
          "     A register that reads ~ (your applied volts x 10) is a voltage register.")


# ===========================================================================
# watch - live movement monitor while you turn the supply knob
# ===========================================================================
def cmd_watch(dev, args):
    print(f"Baselining window {args.start}..{args.start + args.count - 1} ...")
    base, _ = dev.snapshot(args.start, args.count)
    if not base:
        sys.exit("No registers answered. Try a smaller --count near 20480.")
    print(f"Baseline captured ({len(base)} registers). Now CHANGE THE VOLTAGE.\n"
          f"Movers (>= {args.threshold} counts) are listed; if none move I still show\n"
          f"the liveliest register + its absolute value, so you can see whether the\n"
          f"meter tracks your source at all. Press Ctrl-C to stop.  [Ctrl-C = exit]\n")

    stats = {}   # addr -> dict(last,min,max,up,down,peak_abs_delta)
    try:
        cycle = 0
        while True:
            cur, t = dev.snapshot(args.start, args.count)
            cycle += 1
            movers = []
            liveliest = None      # (abs_d, addr, base, cur, d) even if below threshold
            for addr, v in cur.items():
                if addr not in base:
                    continue
                d = v - base[addr]
                s = stats.get(addr)
                if s is None:
                    s = stats[addr] = dict(last=v, min=v, max=v, up=0, down=0, peak=0)
                if v > s["last"]:
                    s["up"] += 1
                elif v < s["last"]:
                    s["down"] += 1
                s["last"] = v
                s["min"] = min(s["min"], v)
                s["max"] = max(s["max"], v)
                s["peak"] = max(s["peak"], abs(d))
                rec = (abs(d), addr, base[addr], v, d)
                if liveliest is None or rec[0] > liveliest[0]:
                    liveliest = rec
                if abs(d) >= args.threshold:
                    movers.append(rec)
            movers.sort(reverse=True)
            stamp = time.strftime("%H:%M:%S")
            if movers:
                lines = [f"[{stamp}] cycle {cycle}: {len(movers)} moving -"]
                for _, addr, b, v, d in movers[:args.top]:
                    lines.append(f"    {addr:>6}  {b:>6} -> {v:>6}  (d{d:+d})   "
                                 f"/10={v/10.0:>7.1f}  /100={v/100.0:>7.2f}")
                print("\n".join(lines), flush=True)
            else:
                _, addr, b, v, d = liveliest
                print(f"[{stamp}] cycle {cycle}: nothing moved >= {args.threshold}. "
                      f"Liveliest {addr}={v} (/10={v/10.0:.1f}V, d{d:+d}).", flush=True)
                if cycle % 8 == 0:
                    print("    >> If /10 does not match the volts you're applying, the "
                          "meter\n       is NOT measuring your source. Check: is it AC? "
                          "is the supply\n       wired to the VOLTAGE terminals (not "
                          "current)? Try `hunt` for a\n       wide before/after diff.",
                          flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass

    ranked = sorted(stats.items(), key=lambda kv: kv[1]["peak"], reverse=True)
    moved = [(a, s) for a, s in ranked if s["peak"] >= args.threshold]
    print("\n\n=== WATCH SUMMARY (biggest swing first) ===")
    if not moved:
        top = ranked[0] if ranked else None
        print("NOT ONE register moved while you changed the supply.\n"
              "That means this window does not reflect your source. Likely causes:\n"
              "  1. Source is DC - the DKM-440 measures True-RMS AC only.\n"
              "  2. Supply wired to the wrong terminals (current input, or wrong phase).\n"
              "  3. The live/responsive register is OUTSIDE this window.\n"
              "Next: run a wide before/after diff:\n"
              "    python find_register.py hunt --wide\n")
        if top:
            a, s = top
            print(f"(For reference, {a} held ~{s['max']} = {s['max']/10.0:.1f} V the whole "
                  f"time - a fixed value, not your changing source.)")
        return
    print(f"  {'addr':>6} {'swing':>6} {'min':>7} {'max':>7} {'monotonic':>10}  interp(max)")
    print("  " + "-" * 64)
    for addr, s in moved[:args.top]:
        tot = s["up"] + s["down"]
        mono = (max(s["up"], s["down"]) / tot) if tot else 0.0
        print(f"  {addr:>6} {s['peak']:>6} {s['min']:>7} {s['max']:>7} "
              f"{mono:>9.0%}  /10={s['max']/10.0:.1f}  /100={s['max']/100.0:.2f}")
    top_addr = moved[0][0]
    print(f"\nThe top register (addr {top_addr}) is your best candidate. To NAIL the\n"
          f"address + scale with proof, run calibrate:\n"
          f"    python find_register.py calibrate --start {args.start} "
          f"--count {args.count} --label L1")


# ===========================================================================
# hunt - WIDE before/after diff: find the responsive register ANYWHERE
# ===========================================================================
def cmd_hunt(dev, args):
    lo, cnt = args.start, args.count
    print(f"HUNT: baselining {lo}..{lo + cnt - 1} ({cnt} registers)...")
    if cnt > 4000:
        print("  (wide range - the first read may take 30-60 s; dead zones time out.)")
    base = dev.read_window(lo, cnt)
    print(f"  baseline captured: {len(base)} registers answered.\n")
    if not base:
        sys.exit("Nothing answered in that range. Check the port / try a smaller range.")

    print("Now change the supply to a CLEARLY different voltage, let it settle ~2 s,\n"
          "then press Enter to scan for what moved. Commands at the prompt:\n"
          "   Enter = scan & diff vs the ORIGINAL baseline\n"
          "   b     = re-baseline here (start fresh from the current values)\n"
          "   q     = quit\n")
    round_no = 0
    while True:
        try:
            cmd = input(f"[hunt] applied volts now (or just Enter / b / q): ").strip()
        except EOFError:
            break
        if cmd.lower() in ("q", "quit", "exit"):
            break
        if cmd.lower() == "b":
            base = dev.read_window(lo, cnt)
            print(f"  re-baselined ({len(base)} registers).")
            continue
        applied = None
        try:
            applied = float(cmd.replace(",", ".")) if cmd else None
        except ValueError:
            applied = None
        round_no += 1
        cur = dev.read_window(lo, cnt, recover=True)
        changed = [(addr, b, cur[addr]) for addr, b in base.items()
                   if addr in cur and cur[addr] != b]
        changed.sort(key=lambda r: abs(r[2] - r[1]), reverse=True)
        if not changed:
            print(f"  round {round_no}: NOTHING changed across {len(base)} registers.\n"
                  f"    -> your source is not reaching ANY register in this range. "
                  f"Widen it\n       (--wide, or --start/--count) or fix the bench "
                  f"(AC? wiring?).", flush=True)
            continue
        print(f"  round {round_no}: {len(changed)} register(s) changed "
              f"(biggest first):", flush=True)
        print(f"    {'addr':>6} {'before':>7} {'after':>7} {'delta':>7}   "
              f"{'/10 after':>9} {'/100 after':>10}  hint")
        print("    " + "-" * 66)
        for addr, b, a in changed[:args.top]:
            hint = ""
            if applied:
                for sc, lbl in ((10, "/10"), (100, "/100"), (1, "x1")):
                    if abs(a / sc - applied) <= max(1.0, 0.05 * applied):
                        hint = f"~applied ({lbl})"
                        break
            print(f"    {addr:>6} {b:>7} {a:>7} {a - b:>+7}   "
                  f"{a/10.0:>9.1f} {a/100.0:>10.2f}  {hint}", flush=True)
        top = changed[0][1]
        print(f"\n    Best responsive register: {top}. Confirm it with a multi-point fit:\n"
              f"        python find_register.py calibrate --start {top} --count 8 "
              f"--label L1\n", flush=True)


# ===========================================================================
# calibrate - multi-point known-voltage linear fit (the rigorous finder)
# ===========================================================================
def _read_points_csv(path):
    """Load saved calibration points -> list of (applied_V, {addr:raw})."""
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    addrs = [int(h) for h in header[1:]]
    points = []
    for r in rows[1:]:
        if not r:
            continue
        v = float(r[0])
        vals = {a: int(x) for a, x in zip(addrs, r[1:]) if x != ""}
        points.append((v, vals))
    return points


def _write_points_csv(path, points, addrs):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["applied_V"] + [str(a) for a in addrs])
        for v, vals in points:
            w.writerow([v] + [vals.get(a, "") for a in addrs])


def _fit_points(points):
    """Fit every register against applied voltage. Returns a ranked list of dicts."""
    # only registers present in ALL points can be fitted
    common = set.intersection(*[set(vals) for _, vals in points])
    xs = [v for v, _ in points]
    results = []
    for addr in sorted(common):
        ys = [vals[addr] for _, vals in points]
        raw_range = max(ys) - min(ys)
        fit = _linfit(xs, ys)
        if fit is None:
            continue
        m, b, r2 = fit
        scale = nearest_nice_scale(abs(m)) if m != 0 else None
        results.append(dict(addr=addr, m=m, b=b, r2=r2, raw_range=raw_range,
                            scale=scale, ys=ys))
    # rank: best straight-line fit first, then biggest swing (ignore near-constant regs)
    results.sort(key=lambda d: (round(d["r2"], 4), d["raw_range"]), reverse=True)
    return results, xs


def _report_fit(results, xs, label, count_for_hint, start_for_hint):
    if not results:
        print("No register varied across your voltage points. Did the reading actually "
              "change on the meter? Is the source AC?")
        return None
    print(f"\n=== FIT RESULTS for {label}  (applied V: "
          f"{', '.join(f'{x:g}' for x in xs)}) ===\n")
    print(f"  {'addr':>6} {'R^2':>7} {'slope(raw/V)':>13} {'intercept':>10} "
          f"{'scale':>6} {'swing':>6}")
    print("  " + "-" * 58)
    for d in results[:10]:
        sc = d["scale"] if d["scale"] is not None else "-"
        print(f"  {d['addr']:>6} {d['r2']:>7.4f} {d['m']:>13.3f} {d['b']:>10.2f} "
              f"{str(sc):>6} {d['raw_range']:>6}")

    best = results[0]
    print()
    if best["r2"] < 0.98:
        print(f"!  Best fit R^2 = {best['r2']:.4f} is weak. Add more voltage points "
              f"spanning a wider range, hold each steady, and re-run.")
    scale = best["scale"]
    unit = "V"
    reading_at = {x: (best["m"] * x + best["b"]) / scale for x in xs} if scale else {}
    print(f"WINNER: register {best['addr']}  ->  scale {scale}  "
          f"(engineering value = raw / {scale} {unit})")
    print(f"        slope {best['m']:.3f} raw/V, intercept {best['b']:.2f}, "
          f"R^2 {best['r2']:.4f}")
    if reading_at:
        chk = "  ".join(f"{x:g}V->{reading_at[x]:.1f}" for x in xs)
        print(f"        sanity (raw/{scale} vs applied): {chk}")
    print(f"\n  Paste into your map (dkm_map.py style):")
    print(f'    Reg("{label.lower()}", {best["addr"]}, 1, {float(scale):.1f}, '
          f'"{unit}", "{label} voltage", verified=True),   '
          f'# R^2={best["r2"]:.3f}')

    # 32-bit sanity note: if the neighbour co-varies, the value might be a 32-bit pair.
    _thirtytwo_note(results, best)
    return best


def _thirtytwo_note(results, best):
    by_addr = {d["addr"]: d for d in results}
    nbr = by_addr.get(best["addr"] + 1)
    if nbr and nbr["r2"] > 0.9 and nbr["raw_range"] > 3:
        print(f"\n  NOTE: neighbour {best['addr'] + 1} also fits well "
              f"(R^2={nbr['r2']:.3f}). If BOTH move together this value may be a\n"
              f"        32-bit pair (hi at {best['addr']}). On this 440 the voltages "
              f"are 16-bit, so a lone strong fit is the norm - but verify.")


def cmd_calibrate(dev, args):
    _ensure_results()
    label = args.label
    points_path = os.path.join(RESULTS_DIR, f"{label}_points.csv")
    fit_path = os.path.join(RESULTS_DIR, f"{label}_fit.csv")

    if args.replay:
        points = _read_points_csv(args.replay)
        print(f"Replaying {len(points)} saved points from {args.replay}")
        results, xs = _fit_points(points)
        _report_fit(results, xs, label, args.count, args.start)
        _save_fit(fit_path, results, xs)
        return

    print(f"CALIBRATE {label}: window {args.start}..{args.start + args.count - 1} on "
          f"{dev.port}.\n"
          f"Wire your bench supply across the L1 & N terminals, multimeter in parallel.\n"
          f"For each point: set a voltage, let it settle, type the MULTIMETER reading "
          f"(volts).\n"
          f"Enter 3+ spread-out points (e.g. 0, 25, 50). Type 'done' to fit, 'q' to "
          f"quit.\n")

    points = []      # list of (applied_V, {addr:raw})
    all_addrs = None
    while True:
        try:
            s = input(f"  point {len(points) + 1} - applied volts (or done/q): ").strip()
        except EOFError:
            break
        if s.lower() in ("q", "quit", "exit"):
            print("Aborted (no fit).")
            return
        if s.lower() in ("done", "d", "fit", ""):
            if len(points) >= 2:
                break
            print("    need at least 2 points to fit a line - keep going.")
            continue
        try:
            v = float(s.replace(",", "."))
        except ValueError:
            print("    not a number; type e.g. 24.9  (or done / q)")
            continue
        vals, t = dev.snapshot(args.start, args.count)
        if not vals:
            print("    no registers answered - check the port/wiring, try again.")
            continue
        points.append((v, vals))
        all_addrs = sorted(vals) if all_addrs is None else all_addrs
        _write_points_csv(points_path, points, all_addrs)   # persist after every point
        # instant feedback: which registers already track your inputs best so far
        if len(points) >= 2:
            res, xs = _fit_points(points)
            if res:
                b = res[0]
                print(f"    captured {len(vals)} regs. Leading candidate so far: "
                      f"addr {b['addr']} (R^2={b['r2']:.3f}, scale {b['scale']}).")
        else:
            print(f"    captured {len(vals)} registers at {v:g} V.")

    results, xs = _fit_points(points)
    _report_fit(results, xs, label, args.count, args.start)
    _save_fit(fit_path, results, xs)
    print(f"\nSaved points -> {points_path}\nSaved fit    -> {fit_path}")


def _save_fit(path, results, xs):
    _ensure_results()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["addr", "r2", "slope_raw_per_V", "intercept", "nice_scale",
                    "raw_range"] + [f"raw@{x:g}V" for x in xs])
        for d in results:
            w.writerow([d["addr"], f"{d['r2']:.5f}", f"{d['m']:.4f}", f"{d['b']:.3f}",
                        d["scale"], d["raw_range"]] + d["ys"])


# ===========================================================================
# CLI
# ===========================================================================
def build_parser():
    p = argparse.ArgumentParser(
        description="Find DKM-440 registers by injecting a known voltage.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--port", default=dkm_modbus.PORT_DEFAULT, help="serial port (COM13)")
    p.add_argument("--baud", type=int, default=dkm_modbus.BAUD_DEFAULT)
    p.add_argument("--slave", type=int, default=dkm_modbus.SLAVE_DEFAULT,
                   help="Modbus slave / device id (default 1)")
    sub = p.add_subparsers(dest="mode", required=True)

    sp = sub.add_parser("probe", help="quick comms test: read the voltage block")
    sp.set_defaults(func=cmd_probe)

    sc = sub.add_parser("scan", help="dump a window once in all interpretations")
    sc.add_argument("--start", type=int, default=DEF_START)
    sc.add_argument("--count", type=int, default=64)
    sc.set_defaults(func=cmd_scan)

    sw = sub.add_parser("watch", help="live: show registers that move as you change V")
    sw.add_argument("--start", type=int, default=DEF_START)
    sw.add_argument("--count", type=int, default=DEF_COUNT)
    sw.add_argument("--threshold", type=int, default=5,
                    help="min raw change to flag a register (default 5)")
    sw.add_argument("--interval", type=float, default=0.5, help="seconds between reads")
    sw.add_argument("--top", type=int, default=10, help="how many movers to list")
    sw.set_defaults(func=cmd_watch)

    sca = sub.add_parser("calibrate", help="enter known voltages -> best-fit register")
    sca.add_argument("--label", default="L1", help="what you're injecting (L1, L2, ...)")
    sca.add_argument("--start", type=int, default=DEF_START)
    sca.add_argument("--count", type=int, default=DEF_COUNT)
    sca.add_argument("--replay", metavar="POINTS.CSV",
                     help="re-fit previously saved points, no device needed")
    sca.set_defaults(func=cmd_calibrate)
    return p


def main():
    # This meter lives on a Turkish Windows box (console codepage cp1254). Force
    # stdout to UTF-8 with a replace fallback so an odd character can never abort a
    # long calibration run with a UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args()
    # --replay needs no serial port
    if args.mode == "calibrate" and args.replay:
        args.func(None, args)
        return
    dev = DKM(port=args.port, baud=args.baud, slave=args.slave).connect()
    try:
        args.func(dev, args)
    finally:
        dev.close()


if __name__ == "__main__":
    main()
