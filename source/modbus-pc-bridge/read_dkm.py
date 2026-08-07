"""Stage 0 PC bridge: read the DKM-440 over Modbus RTU on COM13.

Two modes:

  python read_dkm.py --scan        # dump raw registers in every interpretation,
                                    # so you can match them to the meter's panel
                                    # and CONFIRM the map in dkm_map.py

  python read_dkm.py               # poll once/second and print decoded values
  python read_dkm.py --loop        # ...keep polling
  python read_dkm.py --auto        # ...also run the auto_logic decision each poll

Serial settings are fixed to what the DKM-440 expects: 19200 baud, 8 data bits,
No parity, 1 stop bit (8N1), slave address 1 — exactly what QModMaster used.

pymodbus has changed its read API across 3.x releases, so the call is wrapped in
a small compatibility shim (`_read_holding`).
"""

import argparse
import sys
import time

import dkm_map

PORT = "COM13"
BAUD = 19200
SLAVE = 1
BLOCK_LEN = 32          # how many registers to read in one request from 0x5000


def make_client():
    from pymodbus.client import ModbusSerialClient
    client = ModbusSerialClient(
        port=PORT, baudrate=BAUD, bytesize=8, parity="N", stopbits=1, timeout=1.0,
        retries=1,   # a wide discovery scan hits unmapped gaps; don't retry 3x each
    )
    if not client.connect():
        sys.exit(f"ERROR: could not open {PORT}. Is the USB-RS485 adapter plugged "
                 f"in and is the COM port free (close QModMaster first)?")
    return client


def _read_holding(client, address, count, slave):
    """Call read_holding_registers across pymodbus 3.x signature variations."""
    fn = client.read_holding_registers
    for kwargs in ({"count": count, "slave": slave},
                   {"count": count, "device_id": slave},
                   {"count": count, "unit": slave}):
        try:
            return fn(address, **kwargs)
        except TypeError:
            continue
    # last resort: positional
    return fn(address, count, slave)


def read_block(client, base=dkm_map.MEAS_BASE, count=BLOCK_LEN):
    rr = _read_holding(client, base, count, SLAVE)
    if rr is None or rr.isError():
        raise RuntimeError(f"Modbus read error from {base}: {rr}")
    return rr.registers


def _write_registers(client, address, values, slave):
    """Write a list of registers with FC16, across pymodbus 3.x signatures.

    Same compatibility dance as `_read_holding`: pymodbus renamed the slave kwarg
    (`slave` -> `device_id` -> `unit`) between minor releases, so we try each in
    turn and fall back to positional. `values` is a plain list of ints.
    """
    fn = client.write_registers
    for kwargs in ({"slave": slave}, {"device_id": slave}, {"unit": slave}):
        try:
            return fn(address, values, **kwargs)
        except TypeError:
            continue
    return fn(address, values, slave)


def _read_range(client, start, end, chunk=100):
    """Read every register in [start, end) into {addr: (value, read_time)}.

    We walk the range in `chunk`-sized bites (Modbus caps a request at 125 regs)
    and stamp EACH chunk with the moment it was read. Those per-address timestamps
    are what let the clock finder compute the exact time gap between the two
    snapshots for each register — so it can demand that a genuine seconds register
    advanced by precisely the elapsed number of seconds, instead of accepting any
    old register that merely changed. Bad chunks are skipped, not fatal.
    """
    out = {}
    a = start
    while a < end:
        n = min(chunk, end - a)
        try:
            rr = _read_holding(client, a, n, SLAVE)
            t = time.time()
            if rr is not None and not rr.isError():
                for k, v in enumerate(rr.registers):
                    out[a + k] = (v, t)
        except Exception:
            pass                      # skip a chunk the device won't serve
        a += n
    return out


def _read_addresses(client, addrs):
    """Read a specific SET of addresses (not a solid range) → {addr: (value, time)}.

    Used by the minute-tracker: after the coarse pass we only care about a few
    candidate neighbourhoods, so we read just those. Consecutive (or near-adjacent)
    addresses are batched into one request; a gap > 8 starts a new request. This
    keeps each sampling pass to well under a second, so we can sample several times
    a minute without the scan itself smearing the seconds we're trying to measure.
    """
    out = {}
    addrs = sorted(set(addrs))
    i = 0
    while i < len(addrs):
        j = i
        while j + 1 < len(addrs) and addrs[j + 1] - addrs[j] <= 8:
            j += 1                     # extend the batch across small gaps
        lo, hi = addrs[i], addrs[j]
        try:
            rr = _read_holding(client, lo, hi - lo + 1, SLAVE)
            t = time.time()
            if rr is not None and not rr.isError():
                for k, v in enumerate(rr.registers):
                    out[lo + k] = (v, t)
        except Exception:
            pass
        i = j + 1
    return out


def _clock_fit(series, per_second):
    """How well a register's time-series matches a clock field, 0.0..1.0.

    `series` = [(read_time, value), ...] for one register across all samples.
    `per_second` = the field's rate: 1.0 for a SECONDS register (advances 1 unit
    per real second), 1/60 for a MINUTES register (1 unit per 60 real seconds).

    We anchor on the first sample and, for every later sample, predict where a real
    field would be — pred = (v0 + rate*(t - t0)) mod 60 — then measure the circular
    distance to the actual value. A field that tracks the wall clock scores ~1.0;
    noise that only looked clock-like in one diff collapses here, because it would
    have to keep matching the predicted trajectory at EVERY sample over minutes.
    """
    if len(series) < 3:
        return 0.0
    t0, v0 = series[0]
    tol = 2 if per_second >= 1.0 else 1        # seconds ±2, minutes ±1
    good = 0
    for t, v in series:
        if not (0 <= v <= 59):
            return 0.0
        pred = (v0 + per_second * (t - t0)) % 60
        if min((v - pred) % 60, (pred - v) % 60) <= tol:
            good += 1
    return good / len(series)


def cmd_track_clock(client, start, end, minutes, per_min):
    """Find the RTC by TRACKING candidate registers across many samples over time.

    Phase 1 (coarse): two full-range reads ~8 s apart shortlist registers that
    advanced roughly like seconds. Phase 2 (track): sample ONLY those candidates'
    neighbourhoods `per_min` times a minute for `minutes` minutes, then keep the one
    whose seconds field fits a wall-clock trajectory AND whose neighbour fits a
    minutes trajectory. Over 3–10 minutes this is essentially impossible to fake.
    """
    print(f"Phase 1: coarse scan {start}..{end} to shortlist seconds candidates...")
    A = _read_range(client, start, end)
    time.sleep(8)
    B = _read_range(client, start, end)
    cands = []
    for addr in sorted(A):
        if addr not in B:
            continue
        a, ta = A[addr]
        b, tb = B[addr]
        if not (0 <= a <= 59 and 0 <= b <= 59) or a == b:
            continue
        expected = round(tb - ta) % 60
        adv = (b - a) % 60
        if min((adv - expected) % 60, (expected - adv) % 60) <= 3:  # loose on purpose
            cands.append(addr)
    if not cands:
        print("Phase 1 found no ticking register at all -> the RTC is not on Modbus.\n"
              "Set the clock from the front panel (menu 11.11); replace the battery.")
        return

    interval = 60.0 / per_min
    n_samples = int(round(minutes * per_min)) + 1
    track = {s + off for s in cands for off in range(-8, 3)
             if start <= s + off < end}
    print(f"Phase 1 shortlist: {len(cands)} candidate(s). Phase 2: sampling their\n"
          f"neighbourhoods {per_min}x/min for {minutes} min = {n_samples} samples\n"
          f"(one every {interval:.0f}s). Sit tight; the clock must keep ticking...")

    series = {}
    t0 = time.time()
    for i in range(n_samples):
        target = t0 + i * interval           # absolute targets so we don't drift
        dt = target - time.time()
        if dt > 0:
            time.sleep(dt)
        for addr, (v, t) in _read_addresses(client, track).items():
            series.setdefault(addr, []).append((t, v))
        print(f"  sample {i+1}/{n_samples}  (+{time.time()-t0:.0f}s)")

    # Rank candidates by how perfectly their seconds field tracked the wall clock.
    scored = sorted(cands, key=lambda s: _clock_fit(series.get(s, []), 1.0),
                    reverse=True)
    labels = ["year", "month", "date", "dow", "hours", "minutes", "seconds"]
    shown = 0
    print("\nResults — seconds-fit and the adjacent minutes-fit (1.00 = perfect):")
    for s in scored:
        sf = _clock_fit(series.get(s, []), 1.0)
        if sf < 0.85:
            break                            # ranked list; the rest are worse
        mf = _clock_fit(series.get(s - 1, []), 1.0 / 60.0)   # minutes sits before seconds
        base = s - 6
        print(f"\n  seconds addr {s}: seconds-fit={sf:.2f}   minutes(@{s-1})-fit={mf:.2f}")
        for off, lbl in enumerate(labels):
            ser = series.get(base + off, [])
            print(f"    {base+off:>6}  {lbl:<8} = {ser[-1][1] if ser else None}")
        print(f"    set with: python read_dkm.py --set-clock --base {base}")
        shown += 1

    if shown == 0:
        print(f"\nAcross {minutes} minutes and {n_samples} samples, NOT ONE register "
              f"tracked\nwall-clock seconds. That is conclusive: this DKM-440 does not "
              f"expose its\nRTC over Modbus. Use the front panel (menu 11.11) and "
              f"replace the battery.")
    else:
        print("\nThe row with seconds-fit≈1.00 AND minutes-fit≈1.00 is the real clock.\n"
              "Confirm month/date/hours against the panel, then use its --set-clock base.")


def cmd_find_clock(client, start, end, wait):
    """Locate the RTC by watching which register TICKS like a seconds counter.

    The meter's clock is running (even if wrong), so exactly one register counts
    0->59 once per second. We snapshot the whole range, wait, snapshot again, and
    flag any register that stayed within 0..59 in BOTH reads but changed — that is
    the seconds field. Its neighbours are minutes/hours/date/month/year, which you
    confirm against the front panel. This needs no manual — it finds the address
    wherever the 440 put it.
    """
    print(f"Scanning {start}..{end} twice, {wait}s apart, for a real seconds counter...")
    snapA = _read_range(client, start, end)          # {addr: (value, read_time)}
    time.sleep(wait)
    snapB = _read_range(client, start, end)

    # PRECISE seconds test. For each address we know exactly WHEN it was read in
    # both passes, so we know its own time gap. A true seconds register must have
    # advanced by that many seconds (mod 60), within ±2 for slop. Random noise that
    # merely wiggles in 0..59 almost never matches the wall-clock advance, so this
    # filter throws out the garbage the old "just changed" test let through.
    cands = []
    for addr in sorted(snapA):
        if addr not in snapB:
            continue
        a, ta = snapA[addr]
        b, tb = snapB[addr]
        if not (0 <= a <= 59 and 0 <= b <= 59):
            continue
        expected = round(tb - ta) % 60           # seconds that really elapsed here
        adv = (b - a) % 60                        # seconds the register actually moved
        if adv == 0:
            continue
        off_by = min((adv - expected) % 60, (expected - adv) % 60)
        if off_by <= 2:
            cands.append(addr)

    if not cands:
        print("\nNo register advanced like a real clock. The DKM-440 does NOT appear to\n"
              "expose its RTC over Modbus (matches 8192=filler, 21830=0). Set the clock\n"
              "from the FRONT PANEL instead:  PROGRAMLAMA -> 11.11 TARİH-SAAT AYARLA.\n"
              "And replace the coin-cell battery, or it resets to 2000 on every power-off.")
        return

    # Rank candidates: the real clock's neighbourhood matches the panel (01/01/2000),
    # i.e. month=1 and date=1 sit just after the base in 430 field order. Score by
    # how date-like the surroundings are, so the genuine clock (if any) floats to top.
    def date_score(sec_addr):
        base = sec_addr - 6                      # 430 order: base=year .. base+6=seconds
        m = snapB.get(base + 1, (None,))[0]
        d = snapB.get(base + 2, (None,))[0]
        h = snapB.get(base + 4, (None,))[0]
        return ((m == 1) + (d == 1) + (h is not None and 0 <= h <= 23))
    cands.sort(key=date_score, reverse=True)

    print(f"\n{len(cands)} register(s) advanced like seconds. Most date-like first:")
    labels = ["year", "month", "date", "dow", "hours", "minutes", "seconds"]
    for sec_addr in cands[:6]:
        base = sec_addr - 6
        print(f"\n  seconds addr {sec_addr}  (base {base}, score {date_score(sec_addr)}):")
        for off, lbl in enumerate(labels):
            va = snapA.get(base + off, (None,))[0]
            vb = snapB.get(base + off, (None,))[0]
            print(f"    {base+off:>6}  {lbl:<8}  {va} -> {vb}")
        print(f"    set with: python read_dkm.py --set-clock --base {base}")
    print("\nUse the block whose month=1, date=1 and hours matches the panel. If NONE\n"
          "of them look like a real date, the RTC isn't on Modbus — use the front panel.")


def cmd_dump(client, start, end, out_path, chunk=100):
    """Phase-0 census: read EVERY register in [start, end) once into a CSV.

    Each row is  addr,value,status  where status is one of:
      ok               the device returned a value (stored in `value`)
      exception        the device answered with a Modbus exception (illegal addr)
      no_response      the device stayed silent until the timeout
      skipped_cmd_area the write-only command block 16385..16404 — reading it
                       only produces timeouts, so it is recorded, not read

    The CSV is written incrementally (flushed each progress tick) and the dump
    RESUMES automatically: if `out_path` already exists, we continue from the
    last address it contains instead of starting over. That makes it safe to
    re-run after a kill/timeout — census of the full 64K space can take a while
    when large regions time out. Categorising ok-values into live/zero/filler
    (0xAAAA) is left to post-processing; this function only records raw truth.
    """
    import csv
    import os

    resume_from = None
    if os.path.exists(out_path):
        with open(out_path, newline="") as f:
            for row in csv.reader(f):
                pass                       # cheap: only need the last row
        if row and row[0] != "addr":
            resume_from = int(row[0]) + 1
    if resume_from is not None:
        start = max(start, resume_from)
        print(f"Resuming existing dump at {start}", flush=True)
    if start >= end:
        print("Nothing to do: dump already covers the requested range.")
        return

    # Write-only command area 16385..16404, reads hang. The skip ends at 16406
    # (not 16405) so chunk starts stay EVEN afterwards: probing showed the 440
    # returns real data only for even-aligned read starts — odd starts fall
    # into a junk/echo handler and the whole chunk comes back as garbage.
    CMD_LO, CMD_HI = 16385, 16406
    f = open(out_path, "a", newline="")
    w = csv.writer(f)
    if resume_from is None:
        w.writerow(["addr", "value", "status"])

    t0 = time.time()
    a = start
    n_ok = n_exc = n_dead = 0
    next_tick = a + 2048
    while a < end:
        if CMD_LO <= a < CMD_HI:
            for k in range(a, min(CMD_HI, end)):
                w.writerow([k, "", "skipped_cmd_area"])
            a = min(CMD_HI, end)
            continue
        n = min(chunk, end - a)
        if a < CMD_LO < a + n:
            n = CMD_LO - a                 # stop the chunk at the command area
        rr = None
        try:
            rr = _read_holding(client, a, n, SLAVE)
        except Exception:
            pass
        if rr is None:
            # A timeout leaves a late half-frame in the buffer that corrupts
            # every later exchange (this is what killed the first census run at
            # 14900: one miss, then 50k "dead" registers that answer fine when
            # probed fresh). Hard-reset the serial session before moving on.
            client.close()
            time.sleep(0.3)
            client.connect()
            try:
                rr = _read_holding(client, a, n, SLAVE)   # one clean retry
            except Exception:
                pass
        if rr is not None and not rr.isError():
            for k, v in enumerate(rr.registers):
                w.writerow([a + k, v, "ok"])
            n_ok += n
        elif rr is not None:               # device answered: exception response
            for k in range(n):
                w.writerow([a + k, "", "exception"])
            n_exc += n
        else:                              # silence until timeout
            for k in range(n):
                w.writerow([a + k, "", "no_response"])
            n_dead += n
        a += n
        time.sleep(0.03)                   # politeness gap; the 440 tarpits a
                                           # master that hammers it back-to-back
        if a >= next_tick or a >= end:
            f.flush()
            pct = 100.0 * (a - start) / (end - start)
            print(f"  {a:>5}/{end}  {pct:5.1f}%   ok={n_ok} exc={n_exc} "
                  f"dead={n_dead}   {time.time()-t0:.0f}s", flush=True)
            next_tick += 2048
    f.close()
    print(f"\nDone: {out_path}  ({n_ok} ok, {n_exc} exception, {n_dead} silent; "
          f"{time.time()-t0:.0f}s total)", flush=True)


def cmd_diff(path_a, path_b):
    """Phase-1 tool: compare two census CSVs and print what changed.

    Workflow: dump once (baseline), change ONE setting on the meter's front
    panel, dump again, then diff. The register that changed IS that setting.
    Registers are compared by (value, status); only differences are printed,
    grouped so a 32-bit pair shows as two adjacent rows.
    """
    import csv

    def load(p):
        out = {}
        with open(p, newline="") as fh:
            for row in csv.DictReader(fh):
                out[int(row["addr"])] = (row["value"], row["status"])
        return out

    A, B = load(path_a), load(path_b)
    both = sorted(set(A) & set(B))
    changed = [k for k in both if A[k] != B[k]]
    only_a = len(set(A) - set(B))
    only_b = len(set(B) - set(A))
    print(f"Compared {len(both)} registers "
          f"({only_a} only in A, {only_b} only in B): {len(changed)} changed.\n")
    for k in changed:
        va, sa = A[k]
        vb, sb = B[k]
        note = "" if sa == sb == "ok" else f"   [{sa} -> {sb}]"
        print(f"  {k:>6}  {va or '-':>7} -> {vb or '-':>7}{note}")
    if not changed:
        print("  (no differences — did the setting actually get saved?)")


def cmd_scan(client):
    base = dkm_map.MEAS_BASE
    block = read_block(client, base, BLOCK_LEN)
    print(f"\nRaw block from {base} (0x{base:04X}), {len(block)} registers.")
    print("Compare each row to the DKM-440 front panel, then edit dkm_map.LIKELY_MAP.\n")
    hdr = f"{'addr':>6} {'hex':>6} {'u16':>7} {'/10':>9} {'/100':>9} {'/1000':>9} {'u32hilo/10':>12}"
    print(hdr)
    print("-" * len(hdr))
    for off in range(len(block)):
        addr = base + off
        it = dkm_map.interpretations(block, base, addr)
        print(f"{addr:>6} {it['raw_hex']:>6} {it['raw_dec']:>7} "
              f"{it['u16/10']:>9} {it['u16/100']:>9} {it['u16/1000']:>9} "
              f"{it.get('u32_hilo/10', ''):>12}")
    print("\nTip: three near-equal /10 values in a row = the three phase voltages.")


def cmd_read(client, loop, run_auto):
    regmap = dkm_map.LIKELY_MAP
    base = dkm_map.MEAS_BASE
    auto = None
    if run_auto:
        import auto_logic
        auto = auto_logic.Controller()
    while True:
        try:
            block = read_block(client, base, BLOCK_LEN)
            values = dkm_map.decode(regmap, base, block)
            line = "  ".join(f"{k}={v}" for k, v in values.items())
            stamp = time.strftime("%H:%M:%S")
            if auto is not None:
                decision = auto.decide(values)
                print(f"[{stamp}] {line}  ->  {decision.state}"
                      f"{'  ACTION:' + decision.action if decision.action else ''}")
            else:
                print(f"[{stamp}] {line}")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] {e}")
        if not loop:
            return
        time.sleep(1.0)


def cmd_set_clock(client, year_two_digit, base=None):
    """Write the PC's current date/time into the meter's RTC block.

    `base` = address of the first RTC register (year). Defaults to the 430 manual's
    8192, but on this 440 that is filler, so pass the address you found with
    --find-clock:  python read_dkm.py --set-clock --base <addr>

    Steps: (1) read the block first and show it, (2) detect the year format if the
    user didn't force it, (3) build the 7-value payload with dkm_map.encode_clock(),
    (4) write it in ONE FC16 transaction so all fields land at the same instant
    (no second/minute rollover between writes), (5) read back and show the result.
    """
    from datetime import datetime

    base = dkm_map.RTC_BASE if base is None else base   # 8192, or your found address
    n = len(dkm_map.RTC_FIELDS)                  # 7 clock registers

    before = read_block(client, base, n)         # current clock, as raw registers
    labels = [f[0] for f in dkm_map.RTC_FIELDS]
    print("RTC before:", dict(zip(labels, before)))

    # Auto-detect the year format from what the meter echoed, unless overridden:
    # a year register reading < 100 means the unit stores a 2-digit year.
    if not year_two_digit and before and before[0] < 100:
        year_two_digit = True
        print("(detected 2-digit year format on this unit)")

    payload = dkm_map.encode_clock(datetime.now(), year_two_digit=year_two_digit)
    print("Writing  :", dict(zip(labels, payload)))

    rr = _write_registers(client, base, payload, SLAVE)
    if rr is None or rr.isError():
        raise RuntimeError(f"Modbus write error to {base}: {rr}")

    after = read_block(client, base, n)          # confirm it stuck
    print("RTC after :", dict(zip(labels, after)))


def main():
    ap = argparse.ArgumentParser(description="DKM-440 Modbus RTU reader (Stage 0)")
    ap.add_argument("--scan", action="store_true",
                    help="dump raw registers in all interpretations to confirm the map")
    ap.add_argument("--loop", action="store_true", help="keep polling every second")
    ap.add_argument("--auto", action="store_true",
                    help="run the auto_logic decision each poll (implies --loop)")
    ap.add_argument("--set-clock", action="store_true",
                    help="write the PC's current date/time into the meter's RTC (8192)")
    ap.add_argument("--year2", action="store_true",
                    help="with --set-clock: send a 2-digit year (YY) instead of full year")
    ap.add_argument("--base", type=int, default=None,
                    help="with --set-clock: RTC start address found via --find-clock")
    ap.add_argument("--dump", metavar="CSV",
                    help="census: read every register in --start..--end once into "
                         "CSV (resumes if the file exists)")
    ap.add_argument("--diff", nargs=2, metavar=("A.CSV", "B.CSV"),
                    help="compare two census CSVs and print changed registers")
    ap.add_argument("--find-clock", action="store_true",
                    help="locate the RTC via a quick two-snapshot seconds diff")
    ap.add_argument("--track-clock", action="store_true",
                    help="locate the RTC by tracking seconds+minutes over several minutes")
    ap.add_argument("--minutes", type=float, default=3.0,
                    help="--track-clock: how many minutes to observe (try 3, then 10)")
    ap.add_argument("--per-min", type=int, default=3,
                    help="--track-clock: samples per minute (default 3 = every 20s)")
    ap.add_argument("--start", type=int, default=0,
                    help="--find-clock: first register to scan (default 0)")
    ap.add_argument("--end", type=int, default=16000,
                    help="--find-clock: last register to scan (default 16000; stays\n"
                         "below the write-only command area at 16385 that times out)")
    ap.add_argument("--wait", type=float, default=6.0,
                    help="--find-clock: seconds between the two scans (default 6)")
    args = ap.parse_args()

    if args.diff:                          # pure file comparison, no serial port
        cmd_diff(args.diff[0], args.diff[1])
        return

    client = make_client()
    try:
        if args.dump:
            cmd_dump(client, args.start, args.end, args.dump)
        elif args.track_clock:
            cmd_track_clock(client, args.start, args.end, args.minutes, args.per_min)
        elif args.find_clock:
            cmd_find_clock(client, args.start, args.end, args.wait)
        elif args.set_clock:
            cmd_set_clock(client, year_two_digit=args.year2, base=args.base)
        elif args.scan:
            cmd_scan(client)
        else:
            cmd_read(client, loop=args.loop or args.auto, run_auto=args.auto)
    finally:
        client.close()


if __name__ == "__main__":
    main()
