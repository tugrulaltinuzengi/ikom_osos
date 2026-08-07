# DKM-440 register map — living document

Fill a row's **status** to `CONFIRMED` when `calibrate` gives R² ≈ 1.000 for it.
Paste the `Reg(...)` line the tool prints into the "confirmed line" column/notes.
Everything starts as `hypothesis` (from the DKM-430 manual / earlier captures).

Serial: **COM13, 19200 8N1, slave id 1**. Measurement base **0x5000 = 20480**,
**16-bit** on this 440 (one value per register), phase voltages **÷10 → volts**.

## Measurement block (0x5000 = 20480+)

| addr | quantity | scale (÷) | how to confirm | status |
|---|---|---|---|---|
| 20480 | L1 phase-neutral voltage | 10 | vary L1, `calibrate --label L1` | hypothesis (reads 262.4 V) |
| 20481 | L2 phase-neutral voltage | 10 | vary L2, `calibrate --label L2` | hypothesis (reads 262.1 V) |
| 20482 | L3 phase-neutral voltage | 10 | vary L3, `calibrate --label L3` | hypothesis (reads 261.2 V) |
| 20483 | L1-L2 line voltage | 10 | vary L1 & L2 | hypothesis (261.8 V) |
| 20484 | L2-L3 line voltage | 10 | vary L2 & L3 | hypothesis (261.7 V) |
| 20485 | L3-L1 line voltage | 10 | vary L3 & L1 | hypothesis (261.3 V) |
| 20486…20491 | more voltage-like slots (all ≈ 262) | 10? | inject on one input, see which moves | unknown |
| ??? | Input-01 current | 10? | inject current via 0.1 A CT, `--label I1` | not located (no CT on bench) |
| ??? | Input-01 active power (kW) | 100? | with V and I applied | not located |
| ??? | Input-01 reactive power (kVAr) | 100? | with V and I applied | not located |
| ??? | Input-01 apparent power (kVA) | 100? | with V and I applied | not located |
| ??? | average phase-neutral voltage | 10? | vary all phases together | not located |
| ??? | grid frequency (Hz) | 100 | vary AC source frequency, look for ~5000 | not located |
| ??? | internal supply voltage | 10 | look for a register ≈ your DC supply ×10 | not located |

> The 430 manual's ordering (current at +6, powers after) is a **hypothesis** for
> the 440 — the block is compressed to 16-bit, so offsets shift. Trust `calibrate`,
> not the manual's offsets.

## Other blocks (from the 430 manual / earlier census — verify on the 440)

| block | addr | R/W | format | meaning | status |
|---|---|---|---|---|---|
| RTC clock | 8192–8198 | R/W | 16-bit | year/month/date/dow/hh/mm/ss | **not on Modbus on this unit** — 8192 read 0xAAAA filler; earlier `--find-clock` found no ticking register. Set from front panel (menu 11.11); replace coin cell. |
| Energy (active) | 12288–12346 | R/W | 32-bit ÷10 | kWh counters | hypothesis |
| Energy (reactive) | 12348–12406 | R/W | 32-bit ÷10 | kVArh counters | hypothesis |
| Digital inputs | 21068 | R | 16-bit | low 2 bits = input states | hypothesis |
| Digital outputs | 21069 | R/W | 16-bit | low 2 bits = relay states | hypothesis |
| Harmonics/THD | 21073+ | R | 16-bit ÷100 | 18-reg blocks, +17 = THD% | hypothesis |
| Fault bitfield | 22351 | R | 32-bit | protection state bits | hypothesis |
| Device identity | 21830 | R | 16-bit | expected 0x0440 | **wrong on this unit** — read 0 |
| Commands | 16385–16404 | W | 16-bit | button/reset/etc. | hypothesis (write-only) |

## Confirmed registers (append as you go)

_Paste the tool's `Reg(...)` line here with the date, e.g.:_

```
# 2026-07-06
# (none confirmed yet — run calibrate to add the first)
```

## Notes / observations

- 2026-07-06: `probe` reads 262 V on 20480–20491, byte-identical to the historical
  capture. Confirm the meter actually tracks the bench source (run `watch` and
  wiggle the supply) before trusting any calibrate run.
- The RTC hunt (the original goal) concluded the clock is **not exposed on Modbus**
  on this unit — set it from the front panel and replace the RTC battery.
