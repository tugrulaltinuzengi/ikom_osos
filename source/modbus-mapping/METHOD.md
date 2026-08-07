# METHOD — finding a register by injecting a known stimulus

## The idea in one line

A measurement register holds `raw = scale × value`. Drive `value` to several
**known** points and record `raw` at each; the register whose `raw` plots a
straight line against your known values **is** that measurement, and the line's
slope **is** the scale.

## Why this beats reading a static dump

On a bench a single source usually feeds every voltage input, so a one-shot read
shows the *same* number in a dozen registers (you see this: 20480–20491 all ≈ 262).
You cannot tell which is "L1". But if you make **only L1** change, then **only the
L1 register moves**. Motion is the discriminator, and a *known* motion lets you
solve for both address and scale at once.

## The math (`_linfit` in `find_register.py`)

For each register we have points `(V_i, raw_i)`. Ordinary least squares fits

```
raw = m·V + b
```

- **m (slope)** = raw counts per volt = the **scale** (10 ⇒ divide by 10 for volts).
- **b (intercept)** ≈ 0 for a genuine linear sensor.
- **R²** = fraction of the register's variation explained by the line. The true
  register scores **≈ 1.000**; noise or unrelated drift scores low. Registers that
  don't vary at all (constant) are skipped — there's no line to fit.

Ranking is by R² first, then by how far the register swung (`raw_range`), so a
perfectly-fitting-but-barely-moving artefact can't beat the real, large-swing
register.

Two well-separated points already pin a line; **3–5 points across a wide range**
(e.g. 0, 25, 50, 10) give a meaningful R² and expose any non-linearity.

## Reading the output

```
  addr     R^2  slope(raw/V)  intercept  scale  swing
 20480  1.0000        10.000       0.00     10    500
 20500  0.7500        -0.020    2624.17      1      1     <- constant-ish, ignore
```

- Top row, R² = 1.0000, slope 10.000, big swing → **that's it**, scale = ÷10.
- The "scale" column snaps the slope to the nearest documented value (1/10/100/1000).
- A paste-ready `Reg("l1", 20480, 1, 10.0, "V", ...)` line is printed for the winner.

## Modes and when to use them

| Mode | Use it to… |
|---|---|
| `probe` | Confirm comms — reads the 6 phase-voltage registers and prints volts. |
| `watch` | See, live, which register(s) move as you turn the knob. Sanity/first pass. |
| `calibrate` | Prove address **and** scale with a multi-point R² fit. The real answer. |
| `scan` | Dump a window once in every interpretation (÷10, ÷100, s16…) to eyeball. |

`calibrate --replay results/L1_points.csv` re-fits saved points **without the
device** — handy to re-analyse or after adding notes.

## Gotchas (read before you distrust a result)

- **AC vs DC.** The 440 is a True-RMS AC analyzer (5–300 VAC). A **DC** bench
  supply may register as ~0 or behave oddly on the voltage inputs. If `watch`
  shows no movement, suspect this first — you probably need an **AC** source.
- **Settling.** The meter RMS-averages over a window. After changing the supply,
  wait **~1–2 s** before recording a calibration point, or the raw will still be
  sliding and your fit degrades.
- **One input at a time.** Isolate the channel you're probing (only L1 varying),
  or several registers move together and the ranking gets muddy.
- **32-bit pairs.** On this 440 the voltages are **16-bit** (one register each).
  If a winner's *neighbour* also fits strongly and they move together, the value
  might be a 32-bit pair (hi word at the lower address) — the tool prints a NOTE
  when it sees this. Confirm by checking whether `raw` ever exceeds 65535.
- **Exclusive port.** Close QModMaster or you'll get "Access is denied" on COM13.
- **Window size.** A 256-register window reads in ~0.6 s here, so a calibration
  point is sub-second. Widen `--count` to bring more of the block into view;
  narrow it if a dead sub-range slows the read.

## Extending past voltage

The same trick maps everything the meter measures:

- **Currents / powers**: inject a known current through a **0.1 A-secondary CT**
  (never direct, never 1 A/5 A CTs — see the capabilities doc, Part E safety),
  `--label I1`, and fit. Power/PF follow once V and I are known.
- **Frequency**: vary the AC source frequency; the register reading ≈ f×100 (÷100
  ⇒ Hz) is grid frequency.
- **Digital I/O / relays**: toggle an input or command a relay and `watch` the
  bit that flips (a step, not a ramp — `watch` still flags it).
