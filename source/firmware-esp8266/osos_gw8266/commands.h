// Command downlink: subscribe, parse, dispatch, ack.
//
// The v0.3 build published telemetry and never listened. Every command below
// is acked - unknown action, bad channel and out-of-range interval all produce
// ok:false with a reason. Silence is never an answer (FW-5).
//
// PubSubClient hands the callback a pointer INTO its own shared rx/tx buffer.
// Publishing the ack overwrites that buffer, so the payload must be fully
// parsed into a JsonDocument before anything is published.
#pragma once

#include <ArduinoJson.h>
#include <PubSubClient.h>
#include "config.h"
#include "fleet.h"
#include "power.h"

// Topic builders. Counterparts: tools/osos_proto.py, TopicRouter.kt.
inline void modemTopic(char* out, size_t n, const char* leaf) {
  snprintf(out, n, "osos/m/%s/%s", CFG_MODEM_ID, leaf);
}

inline void analyzerTopic(char* out, size_t n, const char* aid, const char* leaf) {
  snprintf(out, n, "osos/m/%s/a/%s/%s", CFG_MODEM_ID, aid, leaf);
}

// Result of a dispatch, so the caller owns all publishing.
struct CmdResult {
  bool ok;
  char detail[96];
  bool state_changed;
  bool poll_now;
  int8_t poll_index;   // -1 == all
};

inline CmdResult dispatchCommand(const JsonDocument& doc, Fleet& fleet, Power& power) {
  CmdResult r{false, "", false, false, -1};
  const char* action = doc["action"] | "";
  JsonVariantConst args = doc["args"];

  if (strcmp(action, "ping") == 0) {
    r.ok = true;
    snprintf(r.detail, sizeof r.detail, "alive, %u analyzers, interval %us",
             (unsigned)fleet.count(), (unsigned)power.interval());
    return r;
  }

  if (strcmp(action, "read_now") == 0) {
    const char* aid = args["analyzer"] | "";
    if (strlen(aid) == 0) {
      r.ok = true; r.poll_now = true; r.poll_index = -1;
      snprintf(r.detail, sizeof r.detail, "polling all %u", (unsigned)fleet.count());
      return r;
    }
    const int8_t idx = fleet.indexOf(aid);
    if (idx < 0) {
      snprintf(r.detail, sizeof r.detail, "no such analyzer: %s", aid);
      return r;
    }
    r.ok = true; r.poll_now = true; r.poll_index = idx;
    snprintf(r.detail, sizeof r.detail, "polling %s", aid);
    return r;
  }

  if (strcmp(action, "set_interval") == 0) {
    const uint16_t s = args["seconds"] | 0;
    if (!power.setInterval(s)) {
      snprintf(r.detail, sizeof r.detail, "seconds out of range 1..900");
      return r;
    }
    r.ok = true; r.state_changed = true;
    snprintf(r.detail, sizeof r.detail, "interval=%us", (unsigned)s);
    return r;
  }

  if (strcmp(action, "sleep") == 0) {
    const bool on = args["on"] | false;
    power.setSleep(on);
    r.ok = true; r.state_changed = true;
    snprintf(r.detail, sizeof r.detail, "sleep %s, interval %us",
             on ? "on" : "off", (unsigned)power.interval());
    return r;
  }

  if (strcmp(action, "load") == 0) {
    const uint8_t ch = args["ch"] | 0;
    const bool on = args["on"] | false;
    if (!power.setLoad(ch, on)) {
      snprintf(r.detail, sizeof r.detail, "ch out of range 1..%d", CFG_LOAD_CHANNELS);
      return r;
    }
    r.ok = true; r.state_changed = true;
    snprintf(r.detail, sizeof r.detail, "ch%u %s", (unsigned)ch, on ? "on" : "off");
    return r;
  }

  snprintf(r.detail, sizeof r.detail, "unknown action: %s", action);
  return r;
}
