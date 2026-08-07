// Sleep mode and load channels.
//
// Sleep never uses deep sleep. ESP.deepSleep() drops WiFi, TCP and MQTT, so
// the modem cannot receive its own wake command and its LWT fires - it would
// report itself offline while merely resting. Sleep here means a longer report
// interval plus a lower radio duty cycle, with the broker connection intact.
//
// Loads are deliberately NOT persisted. Defaulting them OFF on boot is
// structural, not a policy someone can forget: auto-reclosing a contactor after
// a power cut should be an explicit decision, never a default.
#pragma once

#include <EEPROM.h>
#include <ESP8266WiFi.h>
#include <stdint.h>
#include "config.h"

struct PersistState {
  uint32_t magic;
  uint8_t  version;
  bool     sleep;
  uint16_t awake_interval_s;
};

static const uint32_t kPersistMagic = 0x4F534F53UL;  // 'OSOS'
static const uint8_t  kPersistVersion = 1;

class Power {
 public:
  void begin() {
    EEPROM.begin(sizeof(PersistState));
    PersistState s;
    EEPROM.get(0, s);
    if (s.magic == kPersistMagic && s.version == kPersistVersion) {
      sleep_ = s.sleep;
      awake_interval_s_ = s.awake_interval_s ? s.awake_interval_s
                                             : CFG_REPORT_INTERVAL_S;
    } else {
      sleep_ = false;
      awake_interval_s_ = CFG_REPORT_INTERVAL_S;
    }

    // Drive the level BEFORE enabling the output, or the pin glitches active
    // for the instant between pinMode() and digitalWrite().
    for (uint8_t i = 0; i < CFG_LOAD_CHANNELS; i++) {
      loads_[i] = false;
      digitalWrite(CFG_LOAD_PINS[i], inactiveLevel());
      pinMode(CFG_LOAD_PINS[i], OUTPUT);
      digitalWrite(CFG_LOAD_PINS[i], inactiveLevel());
    }
    applyRadio();
  }

  bool sleeping() const { return sleep_; }
  uint16_t interval() const { return sleep_ ? CFG_SLEEP_INTERVAL_S : awake_interval_s_; }
  bool load(uint8_t ch) const { return ch < CFG_LOAD_CHANNELS ? loads_[ch] : false; }

  void setSleep(bool on) {
    sleep_ = on;
    applyRadio();
    persist();
  }

  bool setInterval(uint16_t seconds) {
    if (seconds < 1 || seconds > 900) return false;
    awake_interval_s_ = seconds;
    persist();
    return true;
  }

  // ch is 1-based on the wire, 0-based internally.
  bool setLoad(uint8_t ch_1based, bool on) {
    if (ch_1based < 1 || ch_1based > CFG_LOAD_CHANNELS) return false;
    const uint8_t i = ch_1based - 1;
    loads_[i] = on;
    digitalWrite(CFG_LOAD_PINS[i], on ? activeLevel() : inactiveLevel());
    return true;
  }

 private:
  static uint8_t activeLevel()   { return CFG_LOAD_ACTIVE_LOW ? LOW : HIGH; }
  static uint8_t inactiveLevel() { return CFG_LOAD_ACTIVE_LOW ? HIGH : LOW; }

  void applyRadio() {
    // The duty-cycle change (interval 5 s -> 300 s) is the guaranteed saving.
    // The radio mode is a secondary optimisation whose real effect must be
    // measured, not assumed - station mode already defaults to modem sleep.
    WiFi.setSleepMode(sleep_ ? WIFI_MODEM_SLEEP : WIFI_NONE_SLEEP);
  }

  void persist() {
    PersistState s{kPersistMagic, kPersistVersion, sleep_, awake_interval_s_};
    EEPROM.put(0, s);
    EEPROM.commit();
  }

  bool sleep_ = false;
  uint16_t awake_interval_s_ = CFG_REPORT_INTERVAL_S;
  bool loads_[CFG_LOAD_CHANNELS] = {false};
};
