#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "osos_codec.h"

// Meter access for the telemetry task. WHICH registers and how to decode them is the
// active meter profile (profile.h); this file is only the RS-485 transport.
// Simulation (Kconfig) fills the same result structure with synthetic values.

void meter_init(void);

// Read every register of the active profile. The caller holds profile_lock() and
// uses profile_regs()/profile_count() for the keys. res->ok[i] false marks a failed
// read; res->gave_up is set when the sweep stopped early.
void meter_poll(osos_poll_result_t *res);

// One ad-hoc read of `words` registers (profile_test). False on any failure.
bool meter_read_raw(uint8_t fc, uint16_t addr, uint16_t words, uint16_t *out);
