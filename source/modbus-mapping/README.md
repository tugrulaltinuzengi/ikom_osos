# DKM-440 register mapping — by stimulus injection

Reverse-engineer the DATAKOM **DKM-440** Modbus map by feeding a **known voltage**
into one input and letting software find which register moved with it. The tool
recovers both the **register address** and its **scale** (raw ÷ scale = engineering
value), with an R² confidence you can trust.

Everything here is self-contained — it does **not** depend on the older
`../modbus/pc_bridge` code (though the confirmed numbers agree with it).

```
dmk_440.mapping/
  find_register.py   the tool (probe / scan / watch / calibrate)
  dkm_modbus.py      the only file that touches the serial port (COM13, 19200 8N1, id 1)
  MAPPING.md         the living register map — fill it in as you confirm each register
  METHOD.md          the theory: why a linear fit finds the register, and the gotchas
  requirements.txt   pymodbus + pyserial
  results/           calibration output (points + fits) — created on first run
```

## 0. Setup (already done on this machine)

```
python -m pip install -r requirements.txt
```

`pymodbus 3.13` and `pyserial 3.5` are installed and COM13 = `USB-SERIAL CH340`.

> **Close QModMaster (or any other Modbus master) first.** The COM port is
> exclusive — only one program can own it at a time, or you get "Access is denied".

## 1. The bench wiring (what you described)

- Bench **power supply** feeding the meter's voltage input for the channel under
  test, e.g. across **L1 and N**.
- **Multimeter** in parallel so you read the *true* applied voltage.
- Meter powered, RS-485 → USB on **COM13**.

> ⚠ **AC vs DC matters.** The DKM-440 measures **True-RMS AC** (input range
> 5–300 VAC). If your bench supply is **DC**, the AC voltage registers may read ~0
> or not track your changes at all. If the voltage register doesn't move in
> `watch`, that's the first thing to check — you likely need an **AC** source (a
> variac / AC calibrator), not a DC supply. See METHOD.md §"Gotchas".

## 2. Quickstart — four commands

Run each with `-h` for options. Start here:

```
# 1) Comms test — reads the 6 phase-voltage registers at 20480 and prints volts.
python find_register.py probe

# 2) Live movement monitor — turn the supply knob and WATCH which register moves.
#    Prove the meter actually responds before you spend time calibrating.
python find_register.py watch --start 20480 --count 256

# 3) The rigorous finder — enter several known voltages, get the best-fit register.
python find_register.py calibrate --label L1 --start 20480 --count 256

# 4) One-shot dump of a window in every interpretation (eyeball tool).
python find_register.py scan --start 20480 --count 64
```

### The recommended flow for each quantity

1. **`watch`** — change the supply up and down. Confirm exactly one (or a small
   group of) register(s) tracks it. Note the address it suggests. If nothing
   moves, fix the bench (AC? wiring? channel assigned?) before continuing.
2. **`calibrate`** — set 3–5 spread-out voltages (e.g. 0, 25, 50, then back to 10),
   letting each **settle ~2 s**, and type the multimeter reading at each. The tool
   fits every register against your inputs; the one with **R² ≈ 1.000** and a clean
   slope (10 → ÷10 volts) is the answer. It prints a paste-ready `Reg(...)` line.
3. Copy that line into **MAPPING.md** and mark it confirmed.
4. Repeat for L2, L3, then currents/powers (needs a current source through a
   0.1 A-secondary CT — see A.2 in the capabilities doc), frequency, etc.

## 3. What "found the register" looks like

```
WINNER: register 20480  ->  scale 10  (engineering value = raw / 10 V)
        slope 10.000 raw/V, intercept 0.00, R^2 1.0000
        sanity (raw/10 vs applied): 0V->0.0  25V->25.0  50V->50.0
    Reg("l1", 20480, 1, 10.0, "V", "L1 voltage", verified=True),   # R^2=1.000
```

Slope 10 means the register stores `volts × 10`, i.e. read it and divide by 10.

## 4. Current state of this meter (observed just now)

`probe` reads **262 V on every voltage slot** 20480–20491 — the same values as the
historical capture. On a bench with **one source feeding all inputs**, every
voltage register shows the same number, so you **cannot** tell them apart from a
static read. That's exactly why you inject a *changing* voltage on **one** input:
only that input's register(s) will move. (If the numbers are *identical* to weeks
ago even after you change the supply, the meter isn't actually measuring your
source — recheck wiring/AC before calibrating.)

See **MAPPING.md** for the running list of confirmed registers and what's left to
find, and **METHOD.md** for how/why this works.
