# SRS-00 — OSOS Gateway System (meshed spec)

*Supersedes nothing; **binds** SRS-01 (MQTT Meter Gateway) and SRS-02 (Neural Network
from Scratch) into one system spec. Written 2026-07-23. Delivery: **2026-08-06**.*

| Source spec | Where it lives | Role in this system |
|---|---|---|
| **SRS-01** | `osos_emu/docs/SRS_MQTT_METER_GATEWAY.md` (+ PDF) | The gateway: meter → ESP32 → MQTT → head-end |
| **SRS-02** | `neural_net_c/SRS_NEURAL_NETWORK_C.md` (+ PDF) | The recognizer: hand-drawn symbol → command intent |

The two were written as unrelated projects. They are **one product**: SRS-02 is the
*input device* for SRS-01. This document specifies the seam between them, which
neither original spec covers.

---

## 1. System context

```
  ──────────────────── SRS-01 domain ────────────────────

                 ┌─ ethernet, Modbus TCP :502 ──▶ ESP8266     ✅ live
   DKM-440 ──────┤                                    │
   unit id 1     └─ RS-485 RTU, 19200 8N1 ──▶ ESP32-S3      🟡 unproven
                                                      │
                                          MQTT/TLS    ▼
                                            broker  (EMQX :8883)
                                                      │
  ──────────────────── SRS-02 domain ─────────────────┼──────
                                                      ▼
                          phone HMI ── MLP 784-128-10 ── draw → 28×28
                                            │              symbol → cmd
                                            │
                        cmd ────────────────┘  back to the gateway
                         ▲
          the seam this document specifies
```

**Two transports, one contract.** The Ethernet path and the RS-485 path publish
byte-identical MQTT payloads, so the phone app is indifferent to which gateway is
running. The Ethernet path is what actually works today; the RS-485 path is the
one SRS-01 was originally written against. See `docs/BENCH.md` for why an ESP8266
reads Ethernet rather than RS-485.

**Trust direction matters.** The recognizer is a *probabilistic* input sitting in
front of an *industrial actuator*. Everything in §3 exists because of that asymmetry.

---

## 2. Requirement families (inherited, unchanged)

| Family | Count | Origin | Meaning |
|---|---|---|---|
| `FW-1..12` | 12 | SRS-01 §3.1 | Gateway firmware |
| `BR-1..3` | 3 | SRS-01 §3.2 | Broker |
| `HE-1..5` | 5 | SRS-01 §3.3 | PC head-end |
| `NF-1..6` | 6 | SRS-01 §4 | Non-functional |
| `FR/NR` | — | SRS-02 §3/§4 | Network correctness + readability |
| **`MX-1..5`** | 5 | **this document** | **The seam — new** |

---

## 3. `MX-*` — seam requirements (new)

| ID | Requirement | Status |
|---|---|---|
| **MX-1** | **Weight-export parity.** The C++ trainer's weights (`w.bin`) export via `tools/export_weights.py` to `nnc-json-1` (base64 LE float32, arch 784-128-10) and load bit-identically in **both** runtimes: `www/nn.js` and Android `nn/Weights.kt`. One trained artifact, two consumers, zero re-training. | ✅ implemented |
| **MX-2** | **Preprocessing bit-parity.** `draw.js` and `Preprocess.kt` must produce byte-identical 784-vectors from the same stroke input: 280×280 canvas, stroke 20 round cap/join, R-channel, threshold 25, ink ≥ 30, fit-20px block-average, centre-of-mass centring in 28×28. A divergence here silently changes which command fires. | ✅ implemented, ⚠️ **no automated parity test** |
| **MX-3** | **Safety gate — recognition never actuates directly.** Any `scope=gateway` command (ping, read_now, set_interval) requires *both* confidence ≥ 0.90 **and** an explicit human **Send** tap. `scope=local` (view switches) may fire instantly. Writes to the DKM-440 (`relay`, `dkm_write`) are structurally absent from the firmware, not merely flag-disabled. | ✅ implemented |
| **MX-4** | **On-device custom symbols.** 10–15 samples train a logistic head (128→N) over the *frozen* MLP embedding, with ±1/±2px shift augmentation. Gated by head softmax ≥ 0.85 **and** best-sample cosine ≥ 0.80; falls back to pure cosine ≥ 0.93 while a class is undertrained. | ✅ implemented |
| **MX-5** | **Retraining round-trip.** Custom samples export as `label,p0..p783` CSV — the exact format `neural_net_c/src/data_mnist.cpp` ingests — so the full net can be retrained on personal symbols with a wider output layer (phase 2). | ✅ export done, retrain not run |

> **MX-2 is the one real technical debt in the mesh.** Two hand-ported
> implementations of an 8-step pixel pipeline, no test pinning them together.
> A single golden-vector fixture (one stroke → expected 784 bytes, asserted in both
> runtimes) would close it. Cheap, and worth doing before the demo.

---

## 4. Coverage — evidence-based, as of 2026-07-28

Legend: ✅ proven · 🟡 code complete, **unproven on real hardware** · ⛔ not met · ⬜ out of scope (justified)

> **Two builds, one requirement set.** `FW-*` was written against the ESP32-S3
> RS-485 gateway, which has still never run on hardware. The ESP8266 Ethernet
> gateway (`firmware8266`) satisfies the same MQTT contract and *is* running, so
> rows below note which build the evidence comes from wherever they differ. When a
> row says "hardware", it means the ESP8266.

### Gateway firmware
| ID | Status | Note |
|---|---|---|
| FW-1 | 🟡 | Polls the confirmed TEDAŞ float map; only ever run in **sim mode** |
| FW-2 | 🟡 | JSON telemetry, QoS 1 — sim-proven |
| FW-3 | 🟡 | Retained status + LWT — needs acceptance **A2** (power pull) |
| FW-4 | ⬜ partial | `read_now`/`set_interval`/`ping` done. `relay`/`dkm_write` deliberately absent (see MX-3) |
| FW-5 | ✅ | Every command acked; v0.2 rebuilt acks with cJSON (escaping bug fixed) |
| FW-6 | ⬜ | Moot while FW-4 writes are absent |
| FW-7 | 🟡 | NTP + ISO-8601 + `seq` now monotonic per boot regardless of connectivity |
| FW-8 | 🟡 | ESP32-S3: RAM ring buffer, 512 frames, oldest-first flush, `buffered:true`. **Absent on the ESP8266 build** — that board measured ~36 KB free heap before WiFi came up, so the 512-frame design does not fit. `buffered` is honestly reported as `false` there, never faked |
| FW-9 | ⬜ | Wi-Fi only. Cellular = Phase B, explicitly out of this delivery |
| FW-10 | 🟡 | v0.2 esp_timer backoff 1→60 s + TWDT with panic enabled |
| FW-11 | ✅ | `config.js`, `broker.env`, `BROKER.md` all gitignored |
| FW-12 | 🟡 | Link-loss → null values + event; needs acceptance **A4** (cable pull) |

### Broker
| ID | Status | Note |
|---|---|---|
| BR-1 | ✅ **on the ESP8266 build** | `firmware8266` runs TLS 1.3 to `your-deployment.emqxsl.com:8883` with `CFG_TLS_INSECURE=0`, verifying the server against a compiled-in DigiCert Global Root G2 anchor. Handshake confirmed on hardware 2026-07-28. The ESP32-S3 build still defaults to `mqtt://broker.emqx.io:1883` — plaintext, anonymous, public — and remains ⛔ |
| BR-2 | ⛔ | No `gateway`/`headend` split, no ACLs. Both roles share one credential, so the phone and any desktop MQTT client connect as the gateway. **This is now the single weakest point in the system** |
| BR-3 | ✅ | `config.h` gitignored, real credentials in place, verified by a live broker connection |

### PC head-end — superseded by design
| ID | Status | Note |
|---|---|---|
| HE-1 | ⛔ | MQTT ingest never added to `modbus/webapp` |
| HE-2/3 | ⬜ | **Superseded**: the Android app is the head-end. Live values + command acks both land there |
| HE-4 | ✅ | `osos_emu/tools/meter_cmd.py` |
| HE-5 | ⬜ | Android keeps a bounded in-memory history only. No durable store |

> **Recommendation:** formally rewrite HE-* as "phone is the head-end" rather than
> leaving five requirements looking failed. The PC head-end was designed *before*
> the Android app existed; it is superseded, not skipped. Say so in the presentation.

### Non-functional
| ID | Status | Note |
|---|---|---|
| NF-1 | 🟡 | < 2 s command latency never measured on hardware |
| NF-2 | 🟡 | ≤ 1 KB payload plausible, never measured |
| NF-3 | 🟡 | v0.2 addresses every failure mode; none tested physically |
| NF-4 | 🟡 | Transport half met — traffic is TLS-encrypted and the broker is authenticated (BR-1). Authorisation half missing: no role separation, so a leaked gateway credential grants publish rights on every topic (BR-2) |
| NF-5 | ✅ | Modules ≤ ~300 lines, teaching headers present |
| NF-6 | ✅ | ASCII-only console |

### SRS-02
All requirements met and closed: gradient check 1e-9, MNIST 97.65 %, XOR `--trace`
hand-check. Absorbed into this system via MX-1. **No open work.**

---

## 5. Meshed acceptance criteria

Delivery = SRS-01 **Phase A** + the `MX-*` seam, on real hardware.

| # | Criterion | Owner | Status |
|---|---|---|---|
| A1 | Telemetry every 5 s, values match an independent reader ±1 V | hardware | ✅ **met 2026-07-28.** 22/22 registers over 15 consecutive cycles; a PC-side Modbus client read the same `13.2` the gateway published |
| A2 | Power pull → retained status `offline` within keepalive | hardware | ⏳ LWT is registered on connect; the pull itself is untested |
| A3 | All commands round-trip with acks; `set_interval` survives reboot | hardware | ⛔ `cmd`/`ack` are **not implemented on the ESP8266 build** — telemetry is one-way. Blocks the drawing demo |
| A4 | Link loss → null values + event; recovery without reboot | hardware | 🟡 partially shown: with the meter unreachable the gateway published nulls and `meter_ok:false` every cycle, then recovered on its own. The deliberate unplug/replug run is still owed |
| FW-8 | Wi-Fi cut 2 min → buffered, flushed in order, `buffered:true` | hardware | ⬜ out of scope on ESP8266 — heap-bound, see FW-8 above |
| MX-3 | Confirm-tap gate demonstrated: recognition alone never actuates | demo | 🟡 implemented in the app; cannot be shown end to end until A3 exists |
| BR-1 | Gateway runs on TLS 8883, broker authenticated | broker | ✅ met |
| BR-2 | Per-role credentials with publish/subscribe ACLs | broker | ⛔ open |

**The critical path to the demo is A3.** Without `cmd`/`ack` on the ESP8266
build, the drawing recogniser has nothing to actuate and MX-3 cannot be shown.
Everything else on this list is either met or a short bench exercise.

**Phase B (cellular) and Phase C (PC head-end 24 h soak) are out of scope for
2026-08-06** and should be presented as roadmap, not as failures.

---

## 6. Standing constraints

- **C-1/C-2** — one polite master on the RS-485 bus: 19200 8N1, ≥ 30 ms gap, one paced retry
- **C-4** — ⛔ **never read or write the 16385–16406 block**
- **Read budget is fixed by the report interval.** You cannot poll faster to evaluate
  alarms, which is *why* alarm rules live on the phone, over the telemetry stream
- The register map at `modbus/dkm_440_analyze/map.py` is the **single source of
  truth** for value keys. The firmware map is generated from it, never hand-copied
