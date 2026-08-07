// Per-analyzer scheduling for a modem that masters a bus of meters.
//
// The v0.3 firmware polled every register of the single analyzer in one
// blocking pass. With N analyzers that becomes an N x 1.5 s block - at 25
// analyzers, 30-45 s, which is past the 30 s MQTT keepalive, so a large fleet
// would silently cost the broker connection every cycle.
//
// Here loop() polls at most ONE due analyzer per pass. Cadence degrades
// gracefully when the fleet is larger than the interval allows, instead of
// collapsing the uplink.
#pragma once

#include <stdint.h>
#include <string.h>   // strcmp in indexOf(); not pulled in transitively here
#include "config.h"

struct AnalyzerRt {
  uint32_t last_poll_ms;
  uint32_t seq;
  uint8_t  fail_streak;
  bool     link_ok;
  bool     ever_polled;
};

class Fleet {
 public:
  void begin() {
    count_ = sizeof(CFG_ANALYZERS) / sizeof(CFG_ANALYZERS[0]);
    if (count_ > CFG_MAX_ANALYZERS) count_ = CFG_MAX_ANALYZERS;
    for (uint8_t i = 0; i < count_; i++) {
      rt_[i] = AnalyzerRt{0, 0, 0, false, false};
    }
  }

  uint8_t count() const { return count_; }
  const AnalyzerCfg& cfg(uint8_t i) const { return CFG_ANALYZERS[i]; }
  AnalyzerRt& rt(uint8_t i) { return rt_[i]; }

  int8_t indexOf(const char* id) const {
    for (uint8_t i = 0; i < count_; i++) {
      if (strcmp(CFG_ANALYZERS[i].id, id) == 0) return (int8_t)i;
    }
    return -1;
  }

  // Next analyzer whose interval has elapsed, or -1. Round-robin from where
  // the last pass stopped, so one fast analyzer cannot starve the others.
  //
  // ELAPSED-SINCE, NOT AN ABSOLUTE DEADLINE. millis() wraps at ~49.7 days;
  // `millis() >= next_due` breaks across the wrap and hangs the analyzer until
  // reboot, while unsigned subtraction stays correct through it. Same idiom as
  // the existing loop() timing. Do not "simplify" this to a deadline compare.
  int8_t nextDue(uint32_t now_ms, uint16_t interval_override_s) {
    for (uint8_t n = 0; n < count_; n++) {
      const uint8_t i = (uint8_t)((cursor_ + n) % count_);
      const uint16_t interval_s =
          interval_override_s ? interval_override_s : CFG_ANALYZERS[i].interval_s;
      const uint32_t period_ms = (uint32_t)interval_s * 1000UL;
      if (!rt_[i].ever_polled || (now_ms - rt_[i].last_poll_ms) >= period_ms) {
        cursor_ = (uint8_t)((i + 1) % count_);
        return (int8_t)i;
      }
    }
    return -1;
  }

  void markPolled(uint8_t i, uint32_t now_ms, bool ok) {
    rt_[i].last_poll_ms = now_ms;
    rt_[i].ever_polled = true;
    rt_[i].seq++;
    rt_[i].link_ok = ok;
    if (ok) rt_[i].fail_streak = 0;
    else if (rt_[i].fail_streak < 255) rt_[i].fail_streak++;
  }

 private:
  AnalyzerRt rt_[CFG_MAX_ANALYZERS];
  uint8_t count_ = 0;
  uint8_t cursor_ = 0;
};
