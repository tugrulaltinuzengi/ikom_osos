// OSOS gateway, ESP8266 edition.
//
// Reads the DKM-440 over Modbus TCP and republishes it as JSON on MQTT, keeping
// the SRS-01 topic and payload contract byte for byte so the existing Android
// app (osos-hmi) works against it unchanged.
//
//   DKM-440 --ethernet--> LAN <--wifi-- ESP8266 --mqtt--> broker --> phone
//
// Why an ESP8266 is enough here: the meter speaks Modbus TCP on its own ethernet
// port, so this device never touches RS-485. No MAX3485, no DE/RE toggling, no
// 3.5-character frame timing, and - the reason this port is pleasant - UART0
// stays free, so the serial console below is actually usable while it runs.
//
// What it still earns its keep for: the meter is LAN-only and has no business
// being exposed to the internet. This is the WAN bridge - one controlled,
// authenticated egress point that translates registers into JSON.
//
// Build:  see firmware8266/README.md
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>

#include "config.h"
#include "meter_map.h"
#include "modbus_tcp.h"
#include "fleet.h"
#include "power.h"
#include "commands.h"

#if CFG_USE_TLS
WiFiClientSecure net;
#else
WiFiClient net;
#endif

PubSubClient mqtt(net);
ModbusTcp meter;
Fleet fleet;
Power power;

static const char* kFwVersion = "0.4.0-esp8266";

// Topics are built once at boot; see the protocol-v2 schema in the design spec.
static char topic_status[64];
static char topic_event[64];
static char topic_cmd[64];
static char topic_ack[64];
static char topic_registry[64];
static char topic_state[64];

// pollAnalyzer is called from the MQTT callback, which is defined above it.
static void pollAnalyzer(uint8_t idx);

// ---------------------------------------------------------------- time -----
// Every telemetry frame carries an ISO-8601 UTC timestamp (FW-7). If NTP has
// not landed yet we say so rather than publishing a fake 1970 date.
static void isoTimestamp(char* out, size_t n) {
  const time_t now = time(nullptr);
  if (now < 1600000000) {            // clearly pre-sync
    snprintf(out, n, "unsynced");
    return;
  }
  struct tm tm_utc;
  gmtime_r(&now, &tm_utc);
  strftime(out, n, "%Y-%m-%dT%H:%M:%SZ", &tm_utc);
}

// ---------------------------------------------------------------- wifi -----
static void wifiConnect() {
  Serial.printf("wifi: joining %s ", CFG_WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.hostname(CFG_MODEM_ID);
  WiFi.begin(CFG_WIFI_SSID, CFG_WIFI_PASS);

  // Bounded wait. Boot must not hang forever on a missing AP - that was finding
  // #2 against the ESP32 v0.1 firmware and the same mistake is easy to repeat.
  const uint32_t deadline = millis() + 20000;
  while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("wifi: ok  ip=%s  rssi=%d\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.println("wifi: FAILED - will keep retrying in loop()");
  }
}

// ---------------------------------------------------------------- mqtt -----
static void publishStatus(const char* state) {
  JsonDocument doc;                 // ArduinoJson 7: elastic, no size template
  doc["v"] = CFG_PROTOCOL_V;
  doc["state"] = state;
  doc["fw"] = kFwVersion;
  doc["bearer"] = "wifi";
  doc["ip"] = WiFi.localIP().toString();
  doc["rssi"] = WiFi.RSSI();
  doc["heap"] = ESP.getFreeHeap();
  doc["analyzers"] = fleet.count();

  char payload[320];
  const size_t n = serializeJson(doc, payload, sizeof payload);
  mqtt.publish(topic_status, (const uint8_t*)payload, n, true);  // retained
}

// Hardware truth: what this modem actually polls. The app owns names and
// folders on a separate topic and cannot corrupt this one.
static void publishRegistry() {
  JsonDocument doc;
  doc["v"] = CFG_PROTOCOL_V;
  doc["rev"] = 1;
  doc["loads"]["channels"] = CFG_LOAD_CHANNELS;
  JsonArray arr = doc["analyzers"].to<JsonArray>();
  for (uint8_t i = 0; i < fleet.count(); i++) {
    JsonObject o = arr.add<JsonObject>();
    o["id"] = fleet.cfg(i).id;
    o["host"] = fleet.cfg(i).host;
    o["port"] = fleet.cfg(i).port;
    o["unit"] = fleet.cfg(i).unit;
    o["interval"] = fleet.cfg(i).interval_s;
  }

  char payload[1400];
  const size_t n = serializeJson(doc, payload, sizeof payload);
  if (n >= sizeof(payload) - 1) {
    Serial.println("registry TOO LARGE - reduce CFG_ANALYZERS");
    return;
  }
  mqtt.publish(topic_registry, (const uint8_t*)payload, n, true);
}

// Observed state, never requested state: a failed command leaves this
// unchanged, so the app can never show a load as on because a cmd was sent.
static void publishState() {
  JsonDocument doc;
  doc["v"] = CFG_PROTOCOL_V;
  doc["sleep"] = power.sleeping();
  doc["interval"] = power.interval();
  JsonArray loads = doc["loads"].to<JsonArray>();
  for (uint8_t i = 0; i < CFG_LOAD_CHANNELS; i++) loads.add(power.load(i));
  char ts[32];
  isoTimestamp(ts, sizeof ts);
  doc["since"] = ts;

  char payload[256];
  const size_t n = serializeJson(doc, payload, sizeof payload);
  mqtt.publish(topic_state, (const uint8_t*)payload, n, true);
}

static void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  // Parse fully before publishing anything: `payload` points into the shared
  // PubSubClient buffer that publish() will overwrite.
  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, payload, length);

  char id[32] = "?";
  if (!err) {
    const char* cid = doc["id"] | "?";
    strncpy(id, cid, sizeof id - 1);
    id[sizeof id - 1] = '\0';
  }

  CmdResult r;
  if (err) {
    r = CmdResult{false, "", false, false, -1};
    snprintf(r.detail, sizeof r.detail, "bad json: %s", err.c_str());
  } else {
    r = dispatchCommand(doc, fleet, power);
  }

  JsonDocument ack;
  ack["v"] = CFG_PROTOCOL_V;
  ack["id"] = id;
  ack["ok"] = r.ok;
  ack["detail"] = r.detail;
  char out[192];
  const size_t n = serializeJson(ack, out, sizeof out);
  mqtt.publish(topic_ack, (const uint8_t*)out, n, false);
  Serial.printf("cmd %s -> %s (%s)\n", id, r.ok ? "ok" : "REFUSED", r.detail);

  if (r.state_changed) publishState();
  if (r.poll_now) {
    if (r.poll_index < 0) {
      for (uint8_t i = 0; i < fleet.count(); i++) pollAnalyzer(i);
    } else {
      pollAnalyzer((uint8_t)r.poll_index);
    }
  }
}

static bool mqttConnect() {
  if (mqtt.connected()) return true;

  // LWT: if this gateway dies, the broker publishes offline on the retained
  // status topic so the phone stops trusting stale values (FW-3).
  static const char* kWill = "{\"v\":2,\"state\":\"offline\"}";

  Serial.printf("mqtt: connecting to %s:%d ... ", CFG_MQTT_HOST, CFG_MQTT_PORT);
  const bool ok = mqtt.connect(
      CFG_MODEM_ID,
      strlen(CFG_MQTT_USER) ? CFG_MQTT_USER : nullptr,
      strlen(CFG_MQTT_PASS) ? CFG_MQTT_PASS : nullptr,
      topic_status, 1, true, kWill);

  if (ok) {
    Serial.println("ok");
    publishStatus("online");
    mqtt.subscribe(topic_cmd, 1);       // QoS 1; re-subscribed on every reconnect
    publishRegistry();
    publishState();
    Serial.printf("subscribed %s\n", topic_cmd);
  } else {
    Serial.printf("failed rc=%d\n", mqtt.state());
  }
  return ok;
}

// ------------------------------------------------------------- telemetry ---
static void pollAnalyzer(uint8_t idx) {
  const AnalyzerCfg& a = fleet.cfg(idx);
  meter.configure(a.host, a.port, a.unit);

  JsonDocument doc;

  char ts[32];
  isoTimestamp(ts, sizeof ts);
  doc["v"] = CFG_PROTOCOL_V;
  doc["ts"] = ts;
  // Per-analyzer and monotonic per boot, independent of connectivity.
  doc["seq"] = fleet.rt(idx).seq + 1;
  doc["buffered"] = false; // store-and-forward is not in this build - see README

  JsonObject values = doc["values"].to<JsonObject>();

  uint8_t ok_count = 0;
  uint8_t consecutive_fail = 0;
  bool gave_up = false;

  for (uint8_t i = 0; i < kMeterRegCount; i++) {
    float v;
    if (meter.readFloatBE(kMeterRegs[i].address, &v)) {
      values[kMeterRegs[i].key] = serialized(String(v, 3));
      ok_count++;
      consecutive_fail = 0;
    } else {
      // Link loss is data, not silence (FW-12): publish the key as null so the
      // consumer can tell "not read" apart from "read as zero".
      values[kMeterRegs[i].key] = nullptr;

      // Give up early on a dead meter instead of waiting out 22 timeouts. At
      // 500 ms each that was ~33 s of blocking per cycle - long enough that the
      // MQTT keepalive expired and the broker disconnected us, so a dead meter
      // took the uplink down with it. Now the worst case is ~1.5 s.
      if (++consecutive_fail >= 3) {
        for (uint8_t j = i + 1; j < kMeterRegCount; j++) {
          values[kMeterRegs[j].key] = nullptr;
        }
        gave_up = true;
        break;
      }
    }

    delay(kReadGapMs);     // the 440 tarpits a hammering master
    // Feed the MQTT keepalive mid-poll. Without this a slow poll silently costs
    // us the broker connection.
    if (mqtt.connected()) mqtt.loop();
    yield();
  }

  const bool meter_ok = (ok_count > 0);
  doc["meter_ok"] = meter_ok;
  fleet.markPolled(idx, millis(), meter_ok);

  // Always report locally, even with no broker. Reading the meter must not
  // depend on the uplink being up - that was finding #2 against the ESP32 v0.1
  // firmware and it is just as wrong here.
  if (meter_ok) {
    // Supply_Voltage is the first entry in the table, so it is already in hand -
    // re-reading it here would be a needless extra transaction on a device that
    // dislikes being hammered.
    JsonVariant supply = values[kMeterRegs[0].key];
    Serial.printf("%s seq=%lu  %u/%u regs  besleme=%s  heap=%u\n",
                  a.id, (unsigned long)fleet.rt(idx).seq, ok_count, kMeterRegCount,
                  supply.isNull() ? "n/a" : supply.as<String>().c_str(),
                  ESP.getFreeHeap());
  } else {
    Serial.printf("%s seq=%lu  meter DOWN%s (exception 0x%02X)  heap=%u\n",
                  a.id, (unsigned long)fleet.rt(idx).seq,
                  gave_up ? ", gave up after 3 dead reads" : "",
                  meter.lastException(), ESP.getFreeHeap());
  }

  if (!mqtt.connected()) {
    Serial.println("  (broker down - reading anyway, frame dropped)");
    return;
  }

  char topic[96];
  analyzerTopic(topic, sizeof topic, a.id, "telemetry");
  char payload[1400];
  const size_t n = serializeJson(doc, payload, sizeof payload);
  if (!mqtt.publish(topic, (const uint8_t*)payload, n, false)) {
    Serial.printf("  pub FAILED (payload %u B, buffer %u B)\n",
                  (unsigned)n, (unsigned)mqtt.getBufferSize());
  }

  JsonDocument st;
  st["v"] = CFG_PROTOCOL_V;
  st["state"] = meter_ok ? "online" : "fault";
  st["host"] = a.host;
  st["unit"] = a.unit;
  st["last_ok"] = ts;
  st["fail_streak"] = fleet.rt(idx).fail_streak;
  analyzerTopic(topic, sizeof topic, a.id, "status");
  char stp[256];
  const size_t sn = serializeJson(st, stp, sizeof stp);
  mqtt.publish(topic, (const uint8_t*)stp, sn, true);
}

// ------------------------------------------------------------------ main ---
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n\nosos gateway %s\n", kFwVersion);

  modemTopic(topic_status,   sizeof topic_status,   "status");
  modemTopic(topic_event,    sizeof topic_event,    "event");
  modemTopic(topic_cmd,      sizeof topic_cmd,      "cmd");
  modemTopic(topic_ack,      sizeof topic_ack,      "ack");
  modemTopic(topic_registry, sizeof topic_registry, "registry");
  modemTopic(topic_state,    sizeof topic_state,    "state");

  fleet.begin();
  Serial.printf("modem %s masters %u analyzer(s)\n", CFG_MODEM_ID, fleet.count());
  for (uint8_t i = 0; i < fleet.count(); i++) {
    Serial.printf("  %s  %s:%u unit %u  every %us\n",
                  fleet.cfg(i).id, fleet.cfg(i).host, fleet.cfg(i).port,
                  fleet.cfg(i).unit, fleet.cfg(i).interval_s);
  }

  wifiConnect();
  power.begin();      // after wifiConnect: setSleepMode needs the STA up

  configTime(0, 0, "pool.ntp.org", "time.nist.gov");   // UTC, per FW-7

#if CFG_USE_TLS
#if CFG_TLS_INSECURE
  // Encrypts but does NOT verify the broker. Bench only.
  net.setInsecure();
#else
  static BearSSL::X509List ca(CFG_CA_CERT);
  net.setTrustAnchors(&ca);
#endif
  // Buffer sizing is measured, not guessed. BearSSL must hold one whole TLS
  // record; this broker sends a 3-certificate chain, so shrinking the receive
  // buffer blindly breaks the handshake. Only shrink if the server actually
  // negotiates Maximum Fragment Length - that frees ~15 KB when it works.
  if (WiFi.status() == WL_CONNECTED &&
      net.probeMaxFragmentLength(CFG_MQTT_HOST, CFG_MQTT_PORT, 1024)) {
    Serial.println("tls: broker supports MFLN(1024) - using small buffers");
    net.setBufferSizes(1024, 1024);
  } else {
    Serial.println("tls: no MFLN - keeping default 16 KB rx buffer");
  }
  Serial.printf("tls: heap before first handshake %u\n", ESP.getFreeHeap());
#endif

  mqtt.setServer(CFG_MQTT_HOST, CFG_MQTT_PORT);
  // PubSubClient defaults to a 256 byte buffer - far too small for 22 registers.
  mqtt.setBufferSize(1536);
  mqtt.setCallback(onMqttMessage);

  // pollAnalyzer() configures the Modbus target per analyzer now.

  Serial.printf("free heap after setup: %u\n", ESP.getFreeHeap());
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    wifiConnect();
    delay(1000);
    return;
  }

  // Broker retries must not stall the poll loop, so this is time-based rather
  // than a blocking delay().
  if (!mqtt.connected()) {
    static uint32_t last_try_ms = 0;
    if (millis() - last_try_ms >= 5000) {
      last_try_ms = millis();
      mqttConnect();
    }
  } else {
    mqtt.loop();
  }

  // At most one analyzer per pass, so a large fleet degrades its cadence
  // instead of blocking long enough to lose the MQTT keepalive.
  const int8_t due = fleet.nextDue(millis(), power.interval());
  if (due >= 0) pollAnalyzer((uint8_t)due);

  yield();
}
