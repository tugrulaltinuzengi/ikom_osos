#pragma once
// Meter profile for the ESP32 gateway: which registers to read and how to decode
// them (source/meter-profiles/README.md). The DKM-440 is built in; another profile
// can be uploaded over MQTT with the same profile_begin / profile_regs /
// profile_meta / profile_commit commands the ESP8266 gateway understands, and is
// kept in NVS.
//
// Differences from the ESP8266 build (firmware-esp8266/osos_gw8266/profile_store.h):
// one meter, so one stored profile and no assignment; storage is NVS, not files;
// the upload is staged in RAM (this chip has it) and committed in one write.
//
// profile.c has no ESP-IDF dependency except through the three profile_store_*
// hooks below, so firmware-esp32-rs485/tests/ runs it on a PC against the shared
// vectors.
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "cJSON.h"
#include "osos_codec.h"

#define PROFILE_MAX_BLOB 8192

// Storage hooks. ESP-IDF: NVS blobs in namespace "osos" (profile_nvs.c).
bool profile_store_read(const char *key, void *buf, size_t *len);   // *len: capacity in, size out
bool profile_store_write(const char *key, const void *buf, size_t len);
bool profile_store_erase(const char *key);

// The telemetry task reads the active profile while the MQTT task may replace it.
// profile_handle()/profile_init() take this lock themselves; a reader holds it for
// as long as it uses profile_regs(). (ESP-IDF: a mutex, profile_nvs.c. Host tests: no-ops.)
void profile_lock(void);
void profile_unlock(void);

// ESP-IDF only: bring up the "profiles" NVS partition and the lock. Before profile_init().
void profile_nvs_init(void);

// Load the stored profile, or fall back to the built-in. Call once at boot.
void profile_init(void);

// Bumped whenever the active profile is replaced: lets a frame captured under one
// profile be recognised (and dropped) after another has taken over.
uint32_t profile_generation(void);

const osos_pf_header_t *profile_header(void);
const osos_reg_t *profile_regs(void);
int profile_count(void);
osos_timing_t profile_timing(void);
const char *profile_id(void);
bool profile_is_builtin(void);

// The profile's own JSON (display metadata), for the retained `profile` topic.
// -1 when there is none. readBlob copies up to n bytes from offset off.
int profile_blob_size(void);
int profile_blob_read(size_t off, uint8_t *buf, size_t n);

typedef struct {
    bool handled;            // false: not a profile command
    bool ok;
    char detail[96];
    bool changed;            // the active profile changed: republish it, flush buffered frames
    bool want_test;          // profile_test: the caller does the Modbus read
    osos_reg_t test_reg;
    uint8_t test_raw_words;  // > 0: raw dump of that many registers
} profile_result_t;

// profile_begin|regs|meta|commit|delete|list|test. `args` may be NULL.
profile_result_t profile_handle(const char *action, const cJSON *args);

// Ack text for a profile_test once the read has been done.
void profile_describe_test(const profile_result_t *r, const uint16_t *w, uint8_t n,
                           char *out, size_t outn);
