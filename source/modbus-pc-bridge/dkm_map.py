"""DKM-440 Modbus register map + decoder (single source of truth).

This is the one file that defines *what each register means*. Stage 0 (this PC
bridge) and Stage 1 (the ESP32 firmware) both use the SAME map, so the numbers
you confirm here port straight onto the ESP.

--------------------------------------------------------------------------------
THE "DATA-EXTRACTION MYSTERY", IN ONE PARAGRAPH
--------------------------------------------------------------------------------
The meter is a bank of numbered 16-bit registers. You read a block with Modbus
function 0x03 ("read holding registers"). Each register is just an integer; to
turn it into volts/amps you divide by a documented multiplier (`scale`). A value
too big for 16 bits (energy totals) is stored across TWO consecutive registers
(`words = 2`); then you must also know the WORD ORDER (which half comes first).

--------------------------------------------------------------------------------
WHY TWO CANDIDATE MAPS BELOW
--------------------------------------------------------------------------------
The only printed map we have is the DKM-430 manual (430_KUL.pdf p.42), where the
measurement block is 32-bit (2 registers per value). BUT your live DKM-440
capture read three near-equal values at 20480/20481/20482:
    0x0A40=2624, 0x0A3D=2621, 0x0A34=2612  ->  /10  ->  262.4, 262.1, 261.2 V
Three almost-identical numbers = the three phase voltages L1/L2/L3. That only
lines up if the 440 measurement block is **16-bit, one value per register**.

So `LIKELY_MAP` below is the 16-bit hypothesis (voltages are high-confidence;
the rest is marked verified=False). `ALT_MAP_32BIT` is the 430-style fallback.
Use read_dkm.py --scan, compare against the DKM-440's own front-panel reading,
then set verified=True / fix any address once a value matches exactly.
"""

from dataclasses import dataclass


@dataclass
class Reg:
    name: str            # short key used in telemetry JSON
    addr: int            # Modbus register address (decimal)
    words: int           # 1 = 16-bit (one register), 2 = 32-bit (two registers)
    scale: float         # engineering value = raw / scale
    unit: str            # for display only
    label: str           # human description
    signed: bool = False
    word_order: str = "hi_lo"   # only used when words == 2: "hi_lo" or "lo_hi"
    verified: bool = False       # flip to True once it matches the panel


# Base address of the measurement block (QModMaster start address = 20480).
MEAS_BASE = 0x5000   # 20480

# ----------------------------------------------------------------------------
# LIKELY_MAP — 16-bit hypothesis for the DKM-440 (CONFIRM each row on the panel)
# ----------------------------------------------------------------------------
LIKELY_MAP = [
    Reg("vL1",  20480, 1, 10.0, "V",  "Phase L1 voltage", verified=False),
    Reg("vL2",  20481, 1, 10.0, "V",  "Phase L2 voltage", verified=False),
    Reg("vL3",  20482, 1, 10.0, "V",  "Phase L3 voltage", verified=False),
    Reg("vL12", 20483, 1, 10.0, "V",  "L1-L2 voltage",    verified=False),
    Reg("vL23", 20484, 1, 10.0, "V",  "L2-L3 voltage",    verified=False),
    Reg("vL31", 20485, 1, 10.0, "V",  "L3-L1 voltage",    verified=False),
    # --- everything below is a GUESS at offsets; verify with --scan + panel ---
    Reg("i1",   20486, 1, 10.0, "A",  "Input-01 current", verified=False),
    Reg("freq", 20796, 1, 100.0, "Hz", "Grid frequency",  verified=False),
]

# ----------------------------------------------------------------------------
# ALT_MAP_32BIT — DKM-430 manual layout (430_KUL.pdf p.42). Fallback if the
# 440 turns out to use 32-bit measurement registers after all.
# ----------------------------------------------------------------------------
ALT_MAP_32BIT = [
    Reg("vL1",  20480, 2, 10.0,  "V",  "Phase L1 voltage"),
    Reg("vL2",  20482, 2, 10.0,  "V",  "Phase L2 voltage"),
    Reg("vL3",  20484, 2, 10.0,  "V",  "Phase L3 voltage"),
    Reg("vL12", 20486, 2, 10.0,  "V",  "L1-L2 voltage"),
    Reg("vL23", 20488, 2, 10.0,  "V",  "L2-L3 voltage"),
    Reg("vL31", 20490, 2, 10.0,  "V",  "L3-L1 voltage"),
    Reg("i1",   20492, 2, 10.0,  "A",  "Input-01 current"),
    Reg("p1",   20552, 2, 100.0, "kW", "Input-01 active power"),
    Reg("pf1",  20736, 1, 1000.0, "",  "Input-01 power factor (cos)"),
    Reg("freq", 20796, 1, 100.0, "Hz", "Grid frequency"),
]

# Writable command registers (430_KUL.pdf p.41) — used at the remote/override stage.
CMD_RESET_COUNTERS = 16387   # write to reset energy/demand counters
CMD_RESET_DEVICE = 16403

# ----------------------------------------------------------------------------
# Block B — Energy / demand counters (430_KUL.pdf p.41), 32-bit, R/W, /10
# ----------------------------------------------------------------------------
ENERGY_MAP = [
    Reg("eActive",   12288, 2, 10.0, "kWh",   "Input-01 active energy"),
    Reg("eReactive", 12348, 2, 10.0, "kVArh", "Input-01 reactive energy"),
]

# ----------------------------------------------------------------------------
# Block C — Alarm / fault status bitfield (430_KUL.pdf p.45), reg 22351, 32-bit.
# Reading this ONE register gives the meter's own protection state as ready bits.
# ----------------------------------------------------------------------------
FAULT_REG = 22351
FAULT_BITS = {
    0: "overvoltage",
    1: "undervoltage",
    2: "overfrequency",
    3: "underfrequency",
    4: "high_THD_V",
    5: "voltage_imbalance",
    6: "phase_order",
    7: "digital_input_1",
    8: "digital_input_2",
    9: "panel",
    10: "over_temperature",
}

# ----------------------------------------------------------------------------
# Block D — Digital I/O (430_KUL.pdf p.44), low 2 bits each
# ----------------------------------------------------------------------------
DIGITAL_INPUTS = 21068
DIGITAL_OUTPUTS = 21069   # relay / digital-output state

# ----------------------------------------------------------------------------
# Device identity (430_KUL.pdf p.45) — read FIRST to confirm which device.
#
# ⚠️ LIVE-DATA CORRECTION (QModMaster capture): on THIS DKM-440, reading 21830..
# 21861 returned ALL ZEROS. So 21830 is NOT the device-type register on the 440 —
# it is a 430-manual guess that does not hold. Do not trust it. The real device-ID
# lives in the 440 "Device Info" area (manual §16.12) or DATAKOM's official 440 map.
# `verified=False` in spirit: treat both of these as UNCONFIRMED on the 440.
# ----------------------------------------------------------------------------
DEVICE_TYPE = 21830       # 430: 0x0430. On this 440 it read 0 → address is wrong.
FIRMWARE_VERSION = 21831  # 430 firmware register; also read 0 on the 440.

# ----------------------------------------------------------------------------
# Block E — harmonics: per-channel 18-register blocks; offset +17 holds THD %.
# ----------------------------------------------------------------------------
HARMONIC_CHANNELS = {
    "thdV_L1": 21073, "thdV_L2": 21091, "thdV_L3": 21109,
    "thdV_U12": 21127, "thdV_U23": 21145, "thdV_U31": 21163,
    "thdI_1": 21181,
}
THD_OFFSET = 17
THD_SCALE = 100.0


# ============================================================================
# REAL-TIME CLOCK (RTC) — 430_KUL.pdf §16.4 "TARİH-SAAT VE KONUM ALANI".
#
# These are R/W 16-bit registers. Unlike the measurement block (read-only, you
# only decode it), you WRITE these to set the meter's battery-backed clock. Each
# field is a plain integer in one register — no scale, no word-joining. You set
# them with Modbus function 0x06 (write one register) or 0x10 (write many at once).
#
# ⚠️ LIVE-DATA CORRECTION: on this DKM-440, reading 8192 returned 0xAAAA (43690,
# shown as -21846 signed) = the "unmapped/filler" pattern, NOT a year. So the 430's
# 8192 RTC address does NOT hold on the 440. Find the real address with
# `read_dkm.py --find-clock` (it locates the register that ticks like seconds).
# NOTE the meter also has a DEAD RTC backup battery (panel showed 01/01/2000 and a
# "düşük pil gerilimi" alarm) — you can set the clock while powered, but it won't
# survive a power-off until the coin cell is replaced.
#
# Every entry below is (address, field_name, valid_min, valid_max). The address is
# absolute decimal exactly as you type it into QModMaster's "Start Address" box.
# ============================================================================
RTC_BASE = 8192                 # 0x2000. Base of the clock block; year lives here.

# One tuple per clock field, IN REGISTER ORDER starting at RTC_BASE, so that
# `RTC_FIELDS[i]` maps to register `RTC_BASE + i`. Keeping them contiguous and in
# order is what lets `encode_clock()` below emit one flat list for a FC16 write.
RTC_FIELDS = [
    # (name,       min, max)   # register = RTC_BASE + index ; meaning
    ("year",         0, 4095),  # 8192 : year. The panel menu wants the LAST TWO
                                #        digits, but this Modbus field is 0..4095,
                                #        so it may want the FULL year (2026). READ
                                #        it once to see which format the unit echoes.
    ("month",        1,   12),  # 8193 : month 1..12 (1 = January).
    ("date",         1,   31),  # 8194 : day-of-month 1..31.
    ("day_of_week",  0,    6),  # 8195 : weekday 0..6. Convention (which day is 0)
                                #        is device-defined; the RTC often recomputes
                                #        this from the date, so an approximate value
                                #        is usually fine.
    ("hours",        0,   23),  # 8196 : hours in 24-hour form 0..23.
    ("minutes",      0,   59),  # 8197 : minutes 0..59.
    ("seconds",      0,   59),  # 8198 : seconds 0..59. Write this LAST (or use FC16)
                                #        so the minute doesn't roll over mid-sequence.
]

# Location registers (drive the astronomical sunrise/sunset relay). 32-bit each,
# hi-word first (word_order="hi_lo"), R/W. Listed for completeness — not needed
# just to set the clock.
LAT_REG = 8199                  # 8199-8200 : latitude  (32-bit)
LON_REG = 8201                  # 8201-8202 : longitude (32-bit)


def encode_clock(dt, year_two_digit: bool = False) -> list:
    """Turn a Python datetime into the 7-value list to write at RTC_BASE (8192).

    `dt`             : any object with .year/.month/.day/.hour/.minute/.second and
                       .weekday() — i.e. a datetime.datetime. We never import
                       datetime here; the caller passes it, keeping this file
                       dependency-free (same discipline as the rest of the map).
    `year_two_digit` : if True, send YY (2026 -> 26); if False, send the full year.
                       Pick based on what a READ of 8192 shows on your unit.

    Returns a 7-int list in EXACTLY register order [year, month, date, dow, h, m, s]
    so it can be handed straight to `write_registers(8192, payload)` (FC16), or
    written one-by-one with FC06 at 8192,8193,...  Nothing here talks to the bus;
    building the payload and sending it are kept separate on purpose (pure = testable).
    """
    year = dt.year % 100 if year_two_digit else dt.year   # YY vs YYYY, per the flag.
    # dt.weekday(): Python gives Monday=0..Sunday=6. The meter's convention may
    # differ (many RTCs use Sunday=0). We pass Python's value through; the device
    # typically re-derives the weekday from the date, so exactness rarely matters.
    dow = dt.weekday()
    values = [year, dt.month, dt.day, dow, dt.hour, dt.minute, dt.second]
    # Clamp/validate each field against its declared range so a bad value can't be
    # silently written into the clock (e.g. seconds=60 at a rollover instant).
    for (name, lo, hi), v in zip(RTC_FIELDS, values):
        if not (lo <= v <= hi):
            raise ValueError(f"RTC field {name}={v} outside allowed {lo}..{hi}")
    return values


# ============================================================================
# COMMAND REGISTERS — 430_KUL.pdf §16.6 "KOMUT ALANI". WRITE-ONLY (function 0x06).
# Writing a (non-zero) value triggers the action once; there is nothing to read
# back. These are how you make the meter *do* something over the wire.
# ============================================================================
COMMANDS = {
    "button_press":     16385,  # simulate a front-panel button press
    "factory_reset":    16386,  # restore factory settings (destructive!)
    "reset_counters":   16387,  # zero the energy/demand counters  (= CMD_RESET_COUNTERS)
    "enter_boot":       16390,  # jump to bootloader (firmware update)
    "write_energy":     16391,  # commit a written energy-counter value
    "reset_demand":     16392,  # zero the demand registers
    "read_sfm_page":    16401,  # internal: fetch an SFM page
    "auto_calibrate":   16402,  # enter auto-calibration (leave alone unless calibrating)
    "reset_device":     16403,  # soft-reboot the meter          (= CMD_RESET_DEVICE)
    "scope_channel":    16404,  # select which channel the oscilloscope capture uses
}


def decode_faults(reg_value) -> list:
    """Turn the 32-bit reg-22351 bitfield into a list of active fault names."""
    if not reg_value:
        return []
    return [name for bit, name in FAULT_BITS.items() if reg_value & (1 << bit)]


def _combine(hi: int, lo: int, signed: bool) -> int:
    """Join two 16-bit registers into one 32-bit integer (hi is the high word)."""
    val = (hi << 16) | lo
    if signed and val >= 0x80000000:
        val -= 0x100000000
    return val


def _as_signed16(v: int) -> int:
    return v - 0x10000 if v >= 0x8000 else v


def decode(regmap, base: int, block) -> dict:
    """Decode a flat list of 16-bit registers (`block`, starting at `base`)
    into engineering units, according to `regmap`.

    Returns {name: float}. Skips any register that falls outside `block`.
    """
    out = {}
    for r in regmap:
        i = r.addr - base
        if i < 0 or i + r.words > len(block):
            continue
        if r.words == 2:
            hi, lo = (block[i], block[i + 1]) if r.word_order == "hi_lo" \
                else (block[i + 1], block[i])
            raw = _combine(hi, lo, r.signed)
        else:
            raw = _as_signed16(block[i]) if r.signed else block[i]
        out[r.name] = round(raw / r.scale, 3)
    return out


def interpretations(block, base: int, addr: int) -> dict:
    """For ONE register address, show every plausible reading at once, so you
    can eyeball which one matches the meter's front panel. Used by --scan.
    """
    i = addr - base
    if i < 0 or i >= len(block):
        return {}
    w0 = block[i]
    res = {
        "raw_dec": w0,
        "raw_hex": f"0x{w0:04X}",
        "u16/10": round(w0 / 10.0, 3),
        "u16/100": round(w0 / 100.0, 3),
        "u16/1000": round(w0 / 1000.0, 3),
        "s16": _as_signed16(w0),
    }
    if i + 1 < len(block):
        w1 = block[i + 1]
        res["u32_hilo/10"] = round(_combine(w0, w1, False) / 10.0, 3)
        res["u32_lohi/10"] = round(_combine(w1, w0, False) / 10.0, 3)
        res["u32_hilo/100"] = round(_combine(w0, w1, False) / 100.0, 3)
    return res
