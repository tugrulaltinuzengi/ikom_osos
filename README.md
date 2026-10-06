# OSOS — remote meter reading over MQTT

**Handoff to IKOM Bilişim · 2026-08-06**

A DATAKOM DKM-440 power analyser is read over Modbus TCP by an ESP8266,
republished as JSON over MQTT/TLS, and displayed on an Android phone that can
name, group, sleep and load-switch a whole fleet of them.

```
DKM-440 ──ethernet──▶ LAN ◀──wifi── ESP8266 ──MQTT/TLS──▶ broker ──▶ phone
```

This is the only document you need. Everything else in this folder is source,
the app, or the presentation. Read section 1 to see it working in five minutes,
section 3 to understand it, section 4 to run it for real, and section 7 for what
is genuinely unfinished.

---

## Contents

1. [See it working in five minutes — no hardware needed](#1-see-it-working-in-five-minutes)
2. [What is in this folder](#2-what-is-in-this-folder)
3. [How it works](#3-how-it-works)
4. [Running it on real hardware](#4-running-it-on-real-hardware)
5. [Securing the broker — the one open security item](#5-securing-the-broker)
6. [Extending it](#6-extending-it)
7. [Honest status — what is proven and what is not](#7-honest-status)
8. [Rebuilding everything](#8-rebuilding-everything)

---

## 1. See it working in five minutes

No meter, no gateway, no broker account. The simulator is a complete
implementation of the protocol — it is what the app was developed against.

```bash
pip install paho-mqtt
cd source/tools
python fake_fleet.py --modems 3 --analyzers 8
```

Install `app/osos-hmi-0.3.1.apk` on any Android 8+ phone. Open **Settings**, set
the broker to `broker.emqx.io` port `1883`, press **Save & reconnect**. The
Monitor tab fills with three modems and their analyzers. Tap one to open it —
measured values stream for the meter you are watching, not for all 24 at once
(see *Watching one meter at a time* below).

Now drive it from the command line:

```bash
python meter_cmd.py --modem gw-01 ping
python meter_cmd.py --modem gw-01 read_now --analyzer an-01
python meter_cmd.py --modem gw-01 load --ch 3 --on
python meter_cmd.py --modem gw-01 sleep --on
python meter_cmd.py --modem gw-01 load --ch 9 --on    # refused, deliberately
```

Every command is answered. A bad channel, an unknown analyzer and an
out-of-range interval all come back `ok:false` with a reason — **silence is
never an answer**. Exit codes are 0 for accepted, 2 for refused, 3 for no reply,
so this is scriptable.

In the app, try: rename an analyzer with **edit**, give it a folder, then force
close and reopen the app — the name comes back, because it lives on the broker
and not in the phone. Flip **Master sleep** and watch the modems report `ASLEEP`.

> `broker.emqx.io` is a shared public broker. It throttles above a few messages
> a second and anyone can read it. Fine for this demo, wrong for anything real —
> section 4 points it at your own broker.

---

## 2. What is in this folder

| Folder | What |
|---|---|
| `app/` | `osos-hmi-0.3.1.apk` — install and run |
| `presentation/` | the delivery talk, plus the Python that generates it |
| `source/android/` | the Kotlin / Jetpack Compose app, with its 41 unit tests |
| `source/firmware-esp8266/` | **the gateway that runs** — Modbus TCP, Arduino |
| `source/firmware-esp32-rs485/` | the earlier ESP-IDF / RS-485 build, for reference |
| `source/browser-hmi/` | the same HMI as a web page — no install |
| `source/tools/` | protocol module, fleet simulator, command CLI |
| `source/neural-net-c/` | the neural network in C, from scratch, with MNIST data |
| `source/modbus-mapping/` | how an undocumented register map was derived |
| `reference/` | the three SRS documents and the bench photos |

**No credentials are anywhere in this folder.** `config.h`, `BROKER.md`,
`broker.env` and `www/config.js` are excluded by name, and the packaging script
refuses to build the folder at all if a known password appears in the result.
You supply your own — every place one belongs has a `.example` template beside
it.

---

## 3. How it works

### The chain

The meter speaks **Modbus TCP on port 502** over its own Ethernet port, so the
gateway never touches RS-485 — no MAX3485, no direction toggling, no character
timing. On an ESP8266 that matters twice, because the chip has one usable UART
and it is the console. Reading over TCP keeps the serial console free while the
gateway runs.

The gateway earns its place as the **WAN bridge**: the meter is LAN-only and has
no business on the internet. One controlled, authenticated egress point
translates registers into JSON.

### Two rules explain most of the design

**The machine owns the addresses. The operator owns the names.**
A modem publishes what it actually polls on a retained `registry` topic. The app
writes names and folders to a separate retained `labels` topic. They share no
field and no writer, so renaming a meter can never corrupt a Modbus address, and
neither side can lose a race with the other. Renaming moves no data and breaks
no history, because **names are not topic segments**.

**State is observed, never requested.**
A refused command leaves the retained `state` topic unchanged. The app can never
show a load as on merely because a command was sent — only because the modem
reported it on.

### The topic contract

Three implementations build these from one grammar — `source/tools/osos_proto.py`,
the app's `TopicRouter.kt`, and the firmware's `commands.h` — so they cannot
drift apart.

```
osos/m/{mid}/status              retained + LWT   modem alive/dead
osos/m/{mid}/registry            retained         which analyzers exist   (MODEM writes)
osos/m/{mid}/state               retained         sleep, interval, loads  (MODEM writes)
osos/m/{mid}/cmd   ->   /ack                      the command downlink
osos/m/{mid}/event                                sleep enter/exit, load switch
osos/m/{mid}/a/{aid}/telemetry                    the 22 measured values
osos/m/{mid}/a/{aid}/status      retained         per-analyzer link state
osos/m/{mid}/labels              retained         names + folders         (APP writes)
osos/tree                        retained         folder definitions      (APP writes)

osos/{gwId}/telemetry                             legacy v1, still rendered
```

`{mid}` is a modem id (`gw-01`), `{aid}` an analyzer id (`an-01`). Both are flat,
stable machine ids that never change once assigned.

**Commands:** `ping`, `read_now{analyzer}`, `set_interval{seconds}`,
`sleep{on}`, `load{ch,on}`.

### Watching one meter at a time

Identity, state, acks and labels are small and retained, so the app holds those
for the **whole** fleet, always. Telemetry is neither — 24 analyzers at a 5 s
interval is a message every 200 ms, most of it for meters nobody is looking at.
So the app subscribes `osos/m/{mid}/a/+/telemetry` only for the modem it is
working on: the one owning the **selected** analyzer, plus whichever one the
Monitor has open.

The selection is app state, not screen state. It survives switching tabs, which
is what lets alarm rules keep evaluating while you are reading the Alarms tab.
A meter you have not opened shows a dim `—` for its voltage in the fleet tree —
that means *not subscribed*, not *faulty*; health comes from the badge beside
the name, which is fed by the always-on per-analyzer `status` topic.

Settings shows the exact filter list the app is holding at that moment. If a
tile is empty, that card is the first place to look.

### Versioning, and why the old gateway still works

Every modem-published payload carries `"v": 2`. The legacy single-gateway topics
carry no `v` and are therefore v1 by definition. That costs nothing and means the
pre-v2 gateway still appears in the fleet tree, tagged `v1`, with no special case
anywhere in the app. If a firmware update ever goes wrong, the system degrades to
v1 rather than dying.

### Sleep

Sleep is a longer report interval (5 s → 300 s) plus a lower WiFi duty cycle. It
is **never** `ESP.deepSleep()` — that would drop WiFi, TCP and MQTT, so the modem
could not receive its own wake command, and its last-will would fire and report
it dead while it was merely resting. The broker connection stays up throughout,
which is why a wake command is acknowledged in about two seconds instead of after
the sleep interval.

Alarms keep evaluating while asleep. Only the **notification** is suppressed;
everything suppressed is recorded and returned as a digest banner on wake. The
overnight record survives the quiet.

### Load control

Relay channels on the modem's own GPIO — **not** a meter register, so the
DKM-440's command block is never written. Four channels: GPIO14/12/13/5 =
D5/D6/D7/D1. GPIO15/D8 is excluded on purpose: it must be LOW at boot, and a
relay module idling it high stops the board booting at all.

Loads are **not persisted** across reboots. Defaulting them off on boot is
structural rather than a policy someone can forget — re-closing a contactor after
a power cut should be an explicit decision.

There is one more safety property worth knowing: the app can recognise
hand-drawn symbols and turn them into commands, and `load` is deliberately absent
from the bindable action list. **No drawn symbol can ever actuate a relay.**

---

## 4. Running it on real hardware

### The meter

Verified reachable at `192.169.10.74:502`, unit id **1**, with a **DHCP
reservation** on MAC `xx-xx-xx-xx-xx-xx` so it survives a power cycle. Before
that reservation the lease wandered across four addresses and each move silently
blinded the gateway — `CFG_ANALYZERS` is compile-time, so a moved meter means
rescan and reflash. **Reserve the address.**

Word order is **big-endian** (`0x41D4 0000` decodes to 26.5). The meter tarpits
a master that fires requests back to back, so `kReadGapMs = 30` in `meter_map.h`
preserves the gap — removing it makes reads fail intermittently.

Phase voltages read `0.000` on the bench because it is a True-RMS **AC** meter
with nothing on its voltage inputs. That is correct, not a fault.

> `Supply_Voltage` is not a constant — register 260 reads back whatever the bench
> supply is set to. 26.5 V, 13.2 V and 23.35 V have all been recorded and all
> were correct at the time. Do not use it as a regression reference; use the
> register count (22/22) instead.

### The gateway

Copy `source/firmware-esp8266/osos_gw8266/config.h.example` to `config.h` and
fill in WiFi, broker and the analyzer table:

```c
static const AnalyzerCfg CFG_ANALYZERS[] = {
    { "an-01", "192.169.10.74", 502, 1, 5 },   // id, host, port, unit, interval_s
};
#define CFG_MODEM_ID    "gw-01"
#define CFG_LOAD_ACTIVE_LOW  1     // 0 for an active-high relay board or a bare LED
```

Build with `arduino-cli`, ESP8266 core 3.1.2, PubSubClient 2.8, ArduinoJson
7.4.3:

```bash
arduino-cli compile -b esp8266:esp8266:nodemcuv2 \
    --libraries "<your Arduino libraries folder>" \
    source/firmware-esp8266/osos_gw8266
arduino-cli upload -b esp8266:esp8266:nodemcuv2 -p COM11 \
    source/firmware-esp8266/osos_gw8266
```

Two traps worth knowing: **`COM11` admits one program at a time** — close the
serial monitor before flashing — and the analyzer count is **capped at 8 on this
board**, because a retained registry for 25 analyzers is about 1.3 KB against a
1536 B buffer shared with telemetry. The protocol itself has no limit; the
simulator demonstrates 25 per modem.

Measured footprint (v0.4, TLS on): RAM 33,920 / 80,192 (42 %), **IRAM 60,799 /
65,536 (92 %)**, flash 388,320 / 1,048,576 (37 %). IRAM is the tight constraint
on this chip, not flash — about 4.7 KB left. If it ever overflows, the fix is
moving code off an `ICACHE_RAM_ATTR` path, not shrinking logic.

### The phone

Settings → broker host, port, TLS on, username, password → **Save & reconnect**.
Nothing else is broker-specific: no vendor API, no EMQX extension. A bad port or
offline-alarm value is refused with a message rather than quietly replaced by a
default, so the field and the connection can never disagree.

Below that, **Active subscriptions** lists the topic filters the app currently
holds. It is read from the client, not composed for display, so it is the
fastest way to tell a broker/ACL problem from a "not subscribed to that meter"
one.

### TLS

The gateway completes a real TLS 1.3 handshake with `CFG_TLS_INSECURE=0`,
verifying the server against a DigiCert Global Root G2 anchor compiled into
`config.h`. The broker negotiates Maximum Fragment Length, so BearSSL runs with
1 KB receive buffers instead of the default 16 KB — that headroom is the only
reason TLS fits alongside the JSON encoder on this chip.

`CFG_TLS_INSECURE=1` still exists for bench work. It encrypts without
authenticating the server and is **not** acceptable in deployment.

---

## 5. Securing the broker

**This is the one open security item.** Today the gateway and the phone share
one credential, so any device holding it can publish as any other. It matters
more than it used to, because the phone now *publishes* — commands, labels and
the folder tree — not just subscribes.

The topic design already separates the two roles cleanly. The ACL below is what
makes the broker enforce it.

### Users

One user **per modem**, plus one head-end user. The per-modem credential is the
whole point — it is what confines a modem to its own subtree.

| Username | Held by | Goes in |
|---|---|---|
| `gw-01` | the modem | `config.h` (never committed) |
| `headend` | the phone, desktop MQTT clients | app Settings |

Use generated passwords. Do not reuse the current shared credential.

### Rules — for `gw-01`

| # | Permission | Action | Topic |
|---|---|---|---|
| 1 | Allow | Publish | `osos/m/gw-01/#` |
| 2 | Allow | Subscribe | `osos/m/gw-01/cmd` |
| 3 | Deny | All | `#` |

### Rules — for `headend`

| # | Permission | Action | Topic |
|---|---|---|---|
| 1 | Allow | Publish | `osos/m/+/cmd` |
| 2 | Allow | Publish | `osos/m/+/labels` |
| 3 | Allow | Publish | `osos/tree` |
| 4 | Allow | Subscribe | `osos/#` |
| 5 | Deny | All | `#` |

**The deny-all row must be last.** Brokers evaluate top to bottom and stop at the
first match; a deny-all placed first refuses everything.

If the pre-v2 gateway is still running, `gw-01` also needs
`Allow · Publish · osos/dkm440-gw1/#`, placed above the deny-all. Remove it when
that gateway is retired.

### Prove it works

Run this **with the gateway credential**. It must fail.

```python
import paho.mqtt.client as mqtt, time
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.username_pw_set("gw-01", "<gateway password>")
c.tls_set()
c.connect("<your-broker>", 8883, 30)
c.loop_start()
# gw-01 publishing as gw-02 - exactly what the ACL exists to stop
c.publish("osos/m/gw-02/a/an-01/telemetry", '{"v":2}', qos=1)
time.sleep(3)
```

Expected: refused, with an authorization failure in the broker's client log.
Subscribe from a second client to confirm nothing arrived. **If it succeeds, the
deny-all row is misordered** — the single most likely mistake, and it fails
silently in the direction that looks fine.

Then check the other direction: with the `headend` credential, publishing to
`osos/m/gw-01/a/an-01/telemetry` must also be refused. The head-end should not
be able to fabricate a meter reading.

---

## 6. Extending it

| To add | What it costs |
|---|---|
| an analyzer | one line in `CFG_ANALYZERS`, reflash |
| a modem | a different `CFG_MODEM_ID`, its own broker user |
| a different meter | a new `meter_map.h` |

No topic changes, no app rebuild, no migration in any of those cases. A new
analyzer appears in the tree the moment the modem republishes its registry —
named `an-02` until someone names it properly from the phone.

**For a meter whose register map you do not have**, the method used to derive
the DKM-440's is written down and repeatable: `source/modbus-mapping/METHOD.md`.
Scan, record, and fit candidate registers against known values by least squares.
That method is arguably worth more than the map it produced.

### What is already vendor-neutral

The topic grammar, the gateway and the app are not specific to this meter. Only
`meter_map.h` is. Any Modbus TCP field device can go behind this gateway in about
a day once its map is known.

### Wiring the fleet into IKOM Data Manager

Two retained topics carry everything the app knows about naming:
`osos/m/+/labels` and `osos/tree`. A bridge that subscribes to those two, plus
`osos/m/+/a/+/telemetry`, has the whole fleet — identified, named and grouped —
without touching the phone or the gateway.

### Before any production use

**Store-and-forward.** `buffered` is always `false` today and honestly reported
as such: if the uplink drops, those frames are gone. A reader that silently
loses data during a network blip cannot be a system of record. This is the gate
before any billing or compliance use, ahead of every other feature.

The ESP32 build reserves ~55 KB for a 512-frame ring; this board measured 36 KB
free heap *before* WiFi came up, so that design cannot be ported as-is. A smaller
RAM ring or a LittleFS-backed queue on the 4 MB flash is the way in.

**A historian.** 720 frames in RAM is monitoring, not history. Billing and
compliance need durable storage.

**Per-device credentials.** Section 5. Cheap now, expensive after the first
customer site.

---

## 7. Honest status

### Proven on hardware

- 22 / 22 registers read over 15 consecutive cycles, no partial reads
- a PC client read the same value in the same second, over the broker
- TLS 1.3 handshake with the server verified against a pinned root
- the meter's address survives a power cycle

### Proven on an emulator against the simulated fleet

- the fleet tree renders multiple v2 modems **and** a legacy v1 gateway side by
  side, all analyzers live
- renaming an analyzer publishes retained `labels`; a **separate** MQTT client
  reads it back, and it survives force-stopping the app
- every command and every refusal path, including bad channel and unknown
  analyzer
- sleep, then wake — the wake acknowledged in about **two seconds**, not after
  the 300 s interval, which is what proves the connection survived sleep
- with the fleet asleep: alarms fired, **no notification was posted**, each was
  logged as muted, and the wake digest listed them
- `load` is absent from the bindable actions, so no drawn symbol can switch a
  relay

41 unit tests cover the topic grammar, the subscription policy, the fleet
reducer and the alarm mute gate. They run with no device.

### Written and compiles, but has never executed

**Firmware v0.4** — the fleet scheduler, sleep, the four load channels and the
command downlink. It compiles clean with the footprint quoted in section 4, but
the hardware was not available when it was written, so it has never run. Flash
it and work through section 4, then re-check the command round-trip, the
per-analyzer read, sleep and wake, and load switching.

Until then the previous firmware keeps working and the app keeps rendering it as
a v1 gateway. Rollback is a `git checkout` of the firmware folder plus a reflash.

### Open, and said so

- **broker role separation** — section 5, specified and not applied
- **store-and-forward** — `buffered` is always `false`
- **awake-versus-asleep current** — never measured, so no figure is quoted
  anywhere. Station mode already defaults to modem sleep, so part of the saving
  is banked before this change and the honest result may be smaller than
  intuition suggests
- **mains accuracy** never verified against a DMM; the supply channel reads
  about 2 % high and that was not investigated
- **the overnight soak** was never run

Nothing in this document is rounded up. Where a number is quoted it was measured;
where it was not measured, it is absent.

---

## 8. Rebuilding everything

```bash
# the app                          JAVA_HOME must point at a JDK 17
cd source/android && ./gradlew assembleDebug

# its tests - 41, no device needed
cd source/android && ./gradlew testDebugUnitTest

# the gateway
arduino-cli compile -b esp8266:esp8266:nodemcuv2 source/firmware-esp8266/osos_gw8266

# the neural network, and the gradient check that proves the maths
cd source/neural-net-c && make && ./gradcheck && ./mnist

# the presentation
cd presentation/source && python mockups.py && python build.py --final
```

The browser HMI needs no build: copy `source/browser-hmi/config.example.js` to
`config.js`, serve the folder over HTTP, open `index.html`.

### Two environment traps

- **Gradle needs a JDK 17.** If the machine default `java` is JDK 8, Gradle
  fails with a confusing error. Set `JAVA_HOME` explicitly; Android Studio ships
  a suitable JDK at `<studio>/jbr`.
- **`arduino-cli` needs the right library path.** If it cannot find
  `PubSubClient.h`, pass `--libraries <path>` — the path in `arduino-cli.yaml`
  may point somewhere that no longer exists.

---

## License and third-party notes

Original code and documents: MIT, see `LICENSE`. DATAKOM's DKM-440 manuals are
not included (vendor documents). The ESP32 build restores `espressif/esp-modbus`
(Apache-2.0) and `espressif/mdns` from `dependencies.lock` via `idf.py reconfigure`;
they are no longer vendored in git. `source/browser-hmi/mqtt.min.js` is MQTT.js (MIT).
The MNIST data fetched by `source/neural-net-c` has its own terms.
