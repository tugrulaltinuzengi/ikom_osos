// OSOS gateway, ESP8266 edition.
//
// Reads Modbus TCP meters and republishes them as JSON on MQTT, keeping the
// SRS-01 topic and payload contract so the existing Android app (osos-hmi) works
// against it unchanged. WHICH registers are read, and how they are decoded, is a
// meter profile (source/meter-profiles/README.md): the DATAKOM DKM-440 is built
// in, others are uploaded from the app or browser and kept in flash.
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
#include "osos_codec.h"
#include "profile_store.h"
#include "osos_builtin_dkm440.h"
#include "fs_littlefs.h"
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
LittleFsAdapter flashFs;
ProfileStore profiles(flashFs, kBuiltin);

static const char* kFwVersion = "0.5.0-esp8266";

// A sweep that has run this long stops, so the loop is back at mqtt.loop() well
// inside the 30 s keepalive even when the meter answers slowly. Polls never call
// mqtt.loop() themselves: a command arriving mid-poll could swap the profile out
// from under it.
static const uint32_t kPollBudgetMs = 8000;

// Topics are built once at boot; see the protocol-v2 schema in the design spec.
static char topic_status[64];
static char topic_event[64];
static char topic_cmd[64];
static char topic_ack[64];
static char topic_registry[64];
static char topic_state[64];
static char topic_profiles[64];

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
// ------------------------------------------------- streamed publishing -----
// PubSubClient's shared buffer is 1536 B. Telemetry for a 48-register profile and
// a profile's own JSON are larger than that, so they are streamed to the socket
// in small pieces instead of being built in the buffer.
class MqttOut : public Print {
 public:
  explicit MqttOut(PubSubClient& c) : c_(c) {}
  size_t write(uint8_t b) override {
    buf_[n_++] = b;
    if (n_ == sizeof buf_) drain();
    return 1;
  }
  size_t write(const uint8_t* d, size_t len) override {
    for (size_t i = 0; i < len; i++) write(d[i]);
    return len;
  }
  void drain() {
    if (n_) { c_.write(buf_, n_); n_ = 0; }
  }
 private:
  PubSubClient& c_;
  uint8_t buf_[128];
  size_t n_ = 0;
};

static bool publishDoc(const char* topic, const JsonDocument& doc, bool retain) {
  if (!mqtt.beginPublish(topic, measureJson(doc), retain)) return false;
  MqttOut out(mqtt);
  serializeJson(doc, out);
  out.drain();
  return mqtt.endPublish();
}

// Retained `profiles` topic: what is stored, what each analyzer reads with, and
// this gateway's limits.
static void publishProfileList() {
  JsonDocument doc;
  profiles.fillListing(doc);
  publishDoc(topic_profiles, doc, true);
}

// Retained `a/<id>/profile` topic: the analyzer's profile JSON, verbatim, so any
// app can label its values and edit the profile. Cleared if the metadata is gone.
static void publishAnalyzerProfile(uint8_t idx) {
  const char* aid = fleet.cfg(idx).id;
  const char* pid = profiles.effectiveId(aid);
  char topic[96];
  analyzerTopic(topic, sizeof topic, aid, "profile");
  const int size = profiles.blobSize(pid);
  if (size <= 0) {
    mqtt.publish(topic, (const uint8_t*)"", 0, true);       // clears the retained copy
    return;
  }
  if (!mqtt.beginPublish(topic, size, true)) return;
  uint8_t chunk[128];
  for (int off = 0; off < size; off += sizeof chunk) {
    const int n = profiles.readBlob(pid, off, chunk, sizeof chunk);
    if (n <= 0) break;
    mqtt.write(chunk, n);
  }
  mqtt.endPublish();
}

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

// Everything the broker should hear after a profile command changed something.
static void afterProfileCommand(const ProfileResult& pr) {
  if (pr.publish_list) publishProfileList();
  for (uint8_t i = 0; i < fleet.count(); i++) {
    const char* aid = fleet.cfg(i).id;
    const bool usesChanged = pr.changed_profile[0] &&
                             strcmp(profiles.effectiveId(aid), pr.changed_profile) == 0;
    const bool isChanged = pr.changed_analyzer[0] && strcmp(aid, pr.changed_analyzer) == 0;
    if (usesChanged || isChanged) publishAnalyzerProfile(i);
  }
}

// profile_test: one ad-hoc read on a named analyzer, answered in the ack. The
// parsing and the answer text are in profile_store.h; only the Modbus read is here.
static void runProfileTest(const ProfileResult& pr, CmdResult& r) {
  const int8_t ai = fleet.indexOf(pr.test_analyzer);
  if (ai < 0) { r.ok = false; snprintf(r.detail, sizeof r.detail, "no such analyzer"); return; }
  const AnalyzerCfg& a = fleet.cfg((uint8_t)ai);
  meter.configure(a.host, a.port, a.unit);
  meter.setTimeoutMs(500);
  const uint8_t words = pr.test_raw_words ? pr.test_raw_words : osos_type_words(pr.test_reg.type);
  uint16_t w[8];
  if (meter.readRegisters(pr.test_reg.fc, pr.test_reg.address, words, w)) {
    ProfileStore::describeTest(pr, w, words, r.detail, sizeof r.detail);
  } else {
    r.ok = false;
    snprintf(r.detail, sizeof r.detail, "read failed (modbus exception 0x%02X)", meter.lastException());
  }
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
  ProfileResult pr;
  if (err) {
    r = CmdResult{false, "", false, false, -1};
    snprintf(r.detail, sizeof r.detail, "bad json: %s", err.c_str());
  } else {
    pr = profiles.handle(doc["action"] | "", doc["args"]);
    if (pr.handled) {
      r = CmdResult{pr.ok, "", false, false, -1};
      snprintf(r.detail, sizeof r.detail, "%s", pr.detail);
      if (pr.ok && pr.want_test) runProfileTest(pr, r);
    } else {
      r = dispatchCommand(doc, fleet, power);
    }
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

  if (pr.handled && pr.ok) afterProfileCommand(pr);
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
    publishProfileList();
    for (uint8_t i = 0; i < fleet.count(); i++) publishAnalyzerProfile(i);
    Serial.printf("subscribed %s\n", topic_cmd);
  } else {
    Serial.printf("failed rc=%d\n", mqtt.state());
  }
  return ok;
}

// ------------------------------------------------------------- telemetry ---
struct PollCtx { uint32_t started; };

static bool pollRead(void*, uint8_t fc, uint16_t start, uint16_t words, uint16_t* out) {
  return meter.readRegisters(fc, start, words, out);
}

// Between requests: the profile's read gap (some meters tarpit a master that
// fires back to back), and the time budget that keeps the MQTT keepalive alive.
static bool pollIdle(void* ctx, uint16_t gap_ms) {
  delay(gap_ms);
  yield();
  return millis() - static_cast<PollCtx*>(ctx)->started < kPollBudgetMs;
}

static void pollAnalyzer(uint8_t idx) {
  const AnalyzerCfg& a = fleet.cfg(idx);

  const char* pid = profiles.effectiveId(a.id);
  if (!profiles.load(pid)) {            // stored profile unreadable: fall back, don't go silent
    pid = kBuiltin.id;
    profiles.load(pid);
  }
  const osos_timing_t t = profiles.timing();
  const osos_reg_t* regs = profiles.regs();
  const uint8_t nregs = profiles.count();

  meter.configure(a.host, a.port, a.unit);
  meter.setTimeoutMs(t.timeout_ms);

  // Static, not stack: 48 doubles and flags are too much for the ESP8266's 4 KB stack.
  static osos_poll_result_t res;
  PollCtx pc{millis()};
  const osos_io_t io = {pollRead, pollIdle, &pc};
  osos_poll(regs, nregs, &t, &io, &res);

  JsonDocument doc;

  char ts[32];
  isoTimestamp(ts, sizeof ts);
  doc["v"] = CFG_PROTOCOL_V;
  doc["ts"] = ts;
  // Per-analyzer and monotonic per boot, independent of connectivity.
  doc["seq"] = fleet.rt(idx).seq + 1;
  doc["buffered"] = false; // store-and-forward is not in this build - see README
  doc["profile"] = pid;
  doc["profile_rev"] = profiles.header().rev;

  JsonObject values = doc["values"].to<JsonObject>();
  for (uint8_t i = 0; i < nregs; i++) {
    if (res.ok[i]) {
      char num[40];
      osos_format(res.value[i], regs[i].decimals, num, sizeof num);
      values[regs[i].key] = serialized(String(num));
    } else {
      // Link loss is data, not silence (FW-12): publish the key as null so the
      // consumer can tell "not read" apart from "read as zero".
      values[regs[i].key] = nullptr;
    }
  }

  const bool meter_ok = (res.ok_count > 0);
  doc["meter_ok"] = meter_ok;
  fleet.markPolled(idx, millis(), meter_ok);

  // Always report locally, even with no broker. Reading the meter must not
  // depend on the uplink being up - that was finding #2 against the ESP32 v0.1
  // firmware and it is just as wrong here.
  if (meter_ok) {
    Serial.printf("%s seq=%lu  %u/%u regs  profile=%s  heap=%u\n",
                  a.id, (unsigned long)fleet.rt(idx).seq, res.ok_count, nregs, pid,
                  ESP.getFreeHeap());
  } else {
    Serial.printf("%s seq=%lu  meter DOWN%s (exception 0x%02X)  profile=%s  heap=%u\n",
                  a.id, (unsigned long)fleet.rt(idx).seq,
                  res.gave_up ? ", gave up" : "",
                  meter.lastException(), pid, ESP.getFreeHeap());
  }

  if (!mqtt.connected()) {
    Serial.println("  (broker down - reading anyway, frame dropped)");
    return;
  }

  char topic[96];
  analyzerTopic(topic, sizeof topic, a.id, "telemetry");
  if (!publishDoc(topic, doc, false)) {
    Serial.printf("  pub FAILED (payload %u B)\n", (unsigned)measureJson(doc));
  }

  JsonDocument st;
  st["v"] = CFG_PROTOCOL_V;
  st["state"] = meter_ok ? "online" : "fault";
  st["host"] = a.host;
  st["unit"] = a.unit;
  st["last_ok"] = ts;
  st["fail_streak"] = fleet.rt(idx).fail_streak;
  st["profile"] = pid;
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
  modemTopic(topic_profiles, sizeof topic_profiles, "profiles");

  fleet.begin();
  Serial.printf("modem %s masters %u analyzer(s)\n", CFG_MODEM_ID, fleet.count());
  for (uint8_t i = 0; i < fleet.count(); i++) {
    Serial.printf("  %s  %s:%u unit %u  every %us\n",
                  fleet.cfg(i).id, fleet.cfg(i).host, fleet.cfg(i).port,
                  fleet.cfg(i).unit, fleet.cfg(i).interval_s);
  }

  // Profile storage. A board flashed without a filesystem partition still runs on
  // the built-in DKM-440; it just cannot keep uploaded profiles.
  static const char* analyzerIds[CFG_MAX_ANALYZERS];
  for (uint8_t i = 0; i < fleet.count(); i++) analyzerIds[i] = fleet.cfg(i).id;
  Serial.printf("flash fs: %s\n", flashFs.begin() ? "ok" : "MISSING (profiles cannot be stored)");
  profiles.begin(analyzerIds, fleet.count());

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
  // PubSubClient defaults to a 256 byte buffer. 1536 holds the largest incoming
  // command (an 8-register profile chunk) and every small outgoing message;
  // telemetry and profiles are streamed past it (see MqttOut).
  mqtt.setBufferSize(1536);
  mqtt.setKeepAlive(30);
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
