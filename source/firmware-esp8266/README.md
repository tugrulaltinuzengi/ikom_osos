# firmware8266 — OSOS gateway on ESP8266 (Modbus TCP edition)

A second firmware target alongside `firmware/` (the ESP32-S3 / ESP-IDF RS-485 build).
Same MQTT contract, completely different path to the meter.

```
DKM-440 ──ethernet──▶ LAN ◀──wifi── ESP8266 ──MQTT──▶ broker ──▶ phone
```

## Why this exists

The DKM-440 turned out to have its own Ethernet port speaking **Modbus TCP on
port 502**, so the gateway never needs RS-485. That deletes the MAX3485, the A/B
wiring and termination, the DE/RE direction toggling, and the 3.5-character frame
timing — and on an ESP8266 it matters twice over, because that chip has only one
usable hardware UART and it is the programming and console port. Reading over TCP
**keeps the serial console free while the gateway runs**.

What the ESP8266 still earns its keep for: the meter is LAN-only and has no
business being exposed to the internet. This is the WAN bridge — one controlled
egress point that translates Modbus registers into JSON on MQTT.

## Verified facts (2026-07-28)

| | |
|---|---|
| Meter address | `192.169.10.74:502`, unit id **1** |
| Address stability | **DHCP reservation** on MAC `00-00-36-7F-04-55`; survives a power cycle |
| Word order | **big-endian** confirmed (`0x41D4 0000` decodes to 26.5) |
| Board | Ai-Thinker ESP8266, 4 MB flash, CP2102 bridge on **COM11** |
| Gateway address | `192.169.10.75`, plain DHCP — no reservation needed |
| Steady state | 22 / 22 registers, 15 consecutive cycles, no partial reads |

Phase voltages read `0.000` — expected, since the analyzer is a True-RMS **AC**
meter with nothing on its voltage inputs.

> **`Supply_Voltage` is not a constant.** Register 260 reads back whatever the
> variable bench supply is dialled to — 26.5 V, 13.2 V and 23.35 V have all been
> recorded and all were correct at the time. Do not use it as a regression
> reference; use the register count instead. See [`docs/BENCH.md`](../../docs/BENCH.md).

Before the reservation the meter's lease wandered across `.229`, `.32`, `.36` and
`.74`, and each move silently blinded the gateway — `CFG_METER_HOST` is a
compile-time constant, so a moved meter means rescan and reflash.

## Build

`arduino-cli` with the `esp8266:esp8266@3.1.2` core, plus PubSubClient 2.8 and
ArduinoJson 7.4.3.

```bash
cp osos_gw8266/config.h.example osos_gw8266/config.h   # then fill in WiFi + broker
arduino-cli compile --fqbn esp8266:esp8266:nodemcuv2 --output-dir build osos_gw8266
arduino-cli upload  --fqbn esp8266:esp8266:nodemcuv2 -p COM11 osos_gw8266
arduino-cli monitor -p COM11 -c baudrate=115200
```

`config.h` holds WiFi and broker credentials and is **gitignored**. Only
`config.h.example` is committed.

**The library path in `~/.arduinoIDE/arduino-cli.yaml` is stale.** It points at
`C:\Users\altnu\OneDrive\Belgeler\Arduino`, which does not exist — OneDrive lives
on `D:`. Pass the real path explicitly or the build fails on `PubSubClient.h`:

```bash
arduino-cli compile --libraries "D:\OneDrive\Belgeler\Arduino\libraries" \
  -b esp8266:esp8266:nodemcuv2 osos_gw8266
```

**`COM11` admits one program at a time.** A live serial monitor blocks the
upload — close it before flashing, and expect a confusing port error if you
forget.

Current footprint, measured 2026-08-06 with `CFG_USE_TLS=1` (v0.4, protocol v2):

```
RAM   33,920 / 80,192   (42%)
IRAM  60,799 / 65,536   (92%)
flash 388,320 / 1,048,576 (37%)
```

v0.3 was RAM 32,756 (40 %), IRAM 60,151 (91 %), flash 378,928 (36 %) — so the
fleet scheduler, sleep/load control and the command downlink together cost
+1,164 B RAM, +648 B IRAM and +9,392 B flash.

An earlier revision of this file recorded RAM 30,780 (38 %) and flash 268,964
(25 %). Those numbers predate TLS being switched on; BearSSL accounts for the
~110 KB difference. **Note the 92 % IRAM figure — that is the tight constraint
on this board, not flash**, and there are only ~4.7 KB left. If IRAM overflows,
the fix is moving code off any `ICACHE_RAM_ATTR` path, not shrinking logic.

## Files

| File | Purpose |
|---|---|
| `osos_gw8266.ino` | WiFi, MQTT, NTP, poll loop, command callback |
| `fleet.h` | Analyzer table runtime — wrap-safe round-robin scheduler |
| `power.h` | Sleep state and the four load channels |
| `commands.h` | Topic builders, command dispatch, ack |
| `modbus_tcp.h` | Modbus TCP client — MBAP framing, FC03, big-endian float decode |
| `meter_map.h` | The 22 registers, generated from `modbus/dkm_440_analyze/map.py` |
| `config.h.example` | Credential template, analyzer table, load pins |

## Contract (protocol v2)

Every payload this firmware publishes carries `"v": 2`. Topics are defined in
`docs/superpowers/specs/2026-08-04-multi-analyzer-fleet-design.md` and
implemented identically in three places — `commands.h`, `tools/osos_proto.py`
and the app's `TopicRouter.kt`.

- `osos/m/{mid}/status` — retained, plus LWT `offline` if the modem dies
- `osos/m/{mid}/registry` — retained; hardware truth, the analyzers it polls
- `osos/m/{mid}/state` — retained; observed sleep flag, interval, load states
- `osos/m/{mid}/cmd` → `osos/m/{mid}/ack` — the downlink
- `osos/m/{mid}/a/{aid}/telemetry` — `{v, ts, seq, buffered, values{22}, meter_ok}`
- `osos/m/{mid}/a/{aid}/status` — retained; per-analyzer link state

`state` reports what is **observed**, never what was requested: a refused command
leaves it unchanged, so the app can never show a load as on merely because a
command was sent.

A register that fails to read is published as `null` rather than omitted, so a
consumer can tell "not read" from "read as zero" (FW-12).

### Load channels

| Channel | GPIO | NodeMCU pin |
|---|---|---|
| 1 | 14 | D5 |
| 2 | 12 | D6 |
| 3 | 13 | D7 |
| 4 | 5 | D1 |

`CFG_LOAD_ACTIVE_LOW` defaults to 1 — most relay boards switch on a LOW input.
**GPIO15/D8 is excluded on purpose**: it must be LOW at boot, and a relay module
idling it high stops the board booting at all.

Loads are **not** persisted across reboots. Defaulting them OFF on boot is
structural rather than a policy someone can forget — auto-reclosing a contactor
after a power cut should be an explicit decision.

### Sleep

Sleep is a longer report interval (`CFG_SLEEP_INTERVAL_S`, default 300 s) plus
`WIFI_MODEM_SLEEP`. It is **never** `ESP.deepSleep()` — that drops WiFi, TCP and
MQTT, so the modem could not receive its own wake command and its LWT would fire,
reporting it offline while it was merely resting.

## Deliberately not in this build

- **Store-and-forward (FW-8).** The ESP32 build reserves ~55 KB for a 512-frame
  ring. This board measured 36 KB free heap *before* WiFi came up, so that design
  cannot be ported as-is. A smaller RAM ring or a LittleFS-backed queue on the
  4 MB flash is the way in, but it is not here yet. `buffered` is therefore
  always `false` — honestly reported, not faked.

**Commands are no longer on this list.** As of v0.4 the gateway subscribes to
`osos/m/{mid}/cmd` and acks every command it receives — `ping`, `read_now`,
`set_interval`, `sleep`, `load`. An unknown action, a bad channel and an
out-of-range interval all produce `ok:false` with a reason; silence is never an
answer (FW-5).

**TLS is no longer on this list either.** As of 2026-07-28 the gateway completes a real
TLS handshake against EMQX Serverless on port 8883 with `CFG_TLS_INSECURE=0`,
verifying the server against the DigiCert Global Root G2 anchor compiled into
`config.h`:

```
tls: broker supports MFLN(1024) - using small buffers
mqtt: connecting to nba17802.ala.eu-central-1.emqxsl.com:8883 ... ok
```

The broker negotiates Maximum Fragment Length, so BearSSL runs with 1 KB buffers
instead of the default 16 KB — that headroom is what makes TLS fit alongside the
JSON encoder on this chip. `CFG_TLS_INSECURE=1` still exists for bench work; it
encrypts without authenticating the server and **does not** satisfy SRS-01 NF-4.

What NF-4 still lacks is role separation (`BR-2`): gateway and head-end share one
set of credentials, with no publish/subscribe ACL split on the broker.

## Note on the DKM-440's temper

`map.py` warns the meter tarpits a master that fires requests back to back. That
is a property of the device, not the transport, so it survived the move to TCP —
`kReadGapMs = 30` in `meter_map.h` preserves the gap. Removing it will make reads
start failing intermittently.
