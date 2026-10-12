# Meter profiles

A **meter profile** is a JSON document that tells an OSOS gateway how to read one
kind of Modbus meter: which registers, how to decode them, and how the app should
label them. It replaces the compiled-in `meter_map.h`.

One profile format is shared by everything:

| Consumer | Where |
|---|---|
| ESP8266 gateway | `source/firmware-esp8266/osos_gw8266/` (`profile.h`, `profile_cmd.h`) |
| ESP32 gateway | `source/firmware-esp32-rs485/` (same codec, `source/firmware-common/`) |
| Browser HMI + Android app (same web UI) | `source/browser-hmi/meter-map/` |
| PC tools, simulator | `source/tools/meterprofile.py` |

`vectors.json` is the cross-language contract: decode cases, validation cases and
the exact command sequence used to upload a profile. Python, JavaScript and C++
all run the same file in their tests, so the three decoders cannot drift apart.

## Format (schema 1)

```json
{
  "schema": 1,
  "id": "sdm630",
  "name": "Eastron SDM630",
  "vendor": "Eastron",
  "rev": 1,
  "transport": "tcp",
  "timing":   { "read_gap_ms": 20, "timeout_ms": 500, "max_block": 16, "retries": 0 },
  "defaults": { "fc": 4, "type": "f32", "word_order": "big", "byte_order": "big",
                "scale": 1, "offset": 0 },
  "registers": [
    { "key": "Voltage_L1", "address": 0, "unit": "V", "label": "Voltage L1", "decimals": 2 }
  ],
  "views": [ { "id": "overview", "label": "Overview", "keys": ["Voltage_L1"] } ]
}
```

### Top level

| Field | Required | Meaning |
|---|---|---|
| `schema` | yes | Always `1`. |
| `id` | yes | `[a-z0-9][a-z0-9_-]{0,23}`. Stable machine id; the gateway stores it under this name. |
| `name` | yes | Display name, at most 48 characters. |
| `vendor`, `model`, `notes` | no | Display only (`notes` at most 200 characters). |
| `rev` | no | Integer 0-65535, default 1. Bump it when you change the profile. |
| `transport` | no | `tcp` or `rtu`. Informational: the gateway decides what it can speak. |
| `timing` | no | See below. |
| `defaults` | no | Values a register inherits when it does not set its own. |
| `registers` | yes | 1 to 48 entries. |
| `views` | no | Up to 8 named tile pages for the app (`id` is `[A-Za-z0-9][A-Za-z0-9_-]{0,23}`). |

### `timing`

| Field | Default | Range | Meaning |
|---|---|---|---|
| `read_gap_ms` | 30 | 0-2000 | Pause between requests. Some meters stop answering a master that fires requests back to back (the DKM-440 does). |
| `timeout_ms` | 500 | 50-5000 | Per-request timeout. Keep it short: a dead meter must not block the gateway's MQTT keepalive. |
| `max_block` | 1 | 1-64 | Largest number of 16-bit registers read in one request. Adjacent registers are merged into one request up to this size. `1` means one request per register (never smaller than the register itself). |
| `retries` | 0 | 0-3 | Extra attempts per request after a failure. |

`timeout_ms x (retries + 1)` must not exceed 8000: a gateway that sits in one request that long would lose its MQTT connection. A sweep also stops after 8 seconds in total.

### Register

| Field | Default | Meaning |
|---|---|---|
| `key` | required | `[A-Za-z0-9_]{1,31}`, unique in the profile. This is the name in the telemetry JSON. |
| `address` | required | **0-based PDU address**, 0-65535. A manual's `40001` is address `0`; `30001` is address `0` with `fc` 4. |
| `fc` | `defaults.fc` (3) | Function code: `3` holding registers, `4` input registers. |
| `type` | `defaults.type` (`f32`) | `u16 i16 u32 i32 f32 u64 i64 f64`. |
| `word_order` | `defaults.word_order` (`big`) | For types wider than 16 bits: `big` = most significant register first. |
| `byte_order` | `defaults.byte_order` (`big`) | `little` swaps the two bytes inside every register. |
| `scale` | `defaults.scale` (1) | Multiplier. |
| `offset` | `defaults.offset` (0) | Added after scaling. |
| `decimals` | 3 for floats or scaled values, else 0 | Digits published, 0-6. |
| `unit`, `label`, `group` | none | Display only (`unit` at most 8, `label` at most 40, `group` at most 24 characters). |

**value = raw x scale + offset.** A register the manual calls "x10" (the stored
integer is ten times the real value) therefore has `scale: 0.1`. Note this is the
inverse of the convention in `source/modbus-mapping/METHOD.md`, which fits
`raw = scale x value`.

The four 32-bit byte layouts, for the value `26.5` (`0x41D40000`):

| Name | `word_order` | `byte_order` | Registers on the wire |
|---|---|---|---|
| ABCD | big | big | `41D4 0000` |
| CDAB | little | big | `0000 41D4` |
| BADC | big | little | `D441 0000` |
| DCBA | little | little | `0000 D441` |

A float that decodes to NaN or infinity counts as a failed read (published as
`null`), exactly as before.

### Views

`views[].keys` lists register keys shown as tiles, in order. If a profile has no
views the app shows one page with every register.

## Included profiles

* `dkm440.json` - the DATAKOM DKM-440, byte-for-byte what `meter_map.h` produced.
  It is also compiled into the firmware as the fallback when nothing is stored.
* `examples/sdm630.json` - a **different** meter (Eastron SDM630: input registers,
  function code 4, contiguous float32). Addresses follow Eastron's published
  register table; check them against your unit's manual before relying on it.
* `examples/generic-int-scaled.json` - an **illustrative** profile (not a real
  device) showing 16-bit integers, `scale`, `offset` and a 32-bit counter.

## Limits and why

The gateway keeps profiles in flash and reads one into RAM only while polling, so
the limits are about the ESP8266's heap: 48 registers per profile, 6 stored
profiles, 8 KB of display metadata per profile. The gateway announces its actual
limits in the retained `osos/m/{modem}/profiles` topic.
