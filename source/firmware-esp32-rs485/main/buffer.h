#pragma once
// Store-and-forward telemetry buffer (SRS FW-8): frames captured while the
// broker is unreachable are kept in a RAM ring and flushed oldest-first with
// "buffered":true on reconnect. 512 frames x ~108 B = ~55 KB static RAM.
#include <stdbool.h>
#include <stdint.h>
#include "meter.h"

typedef struct {
    int64_t  epoch;     // seconds since Unix epoch at capture time
    uint32_t seq;
    uint32_t ok_mask;   // bit i set = METER_REGS[i] read ok
    bool     meter_ok;  // at least one register answered
    float    vals[METER_NUM_REGS];
} telem_frame_t;

#define TELEM_BUF_CAP 512

// Single-consumer/single-producer from the telemetry task only — no locking.
void buf_push(const telem_frame_t *f);  // drops the oldest frame when full
bool buf_pop(telem_frame_t *f);         // oldest first; false when empty
int  buf_count(void);
