#pragma once
// Store-and-forward telemetry buffer (SRS FW-8): frames captured while the
// broker is unreachable are kept in a RAM ring and flushed oldest-first with
// "buffered":true on reconnect. CONFIG_OSOS_BUFFER_FRAMES x ~410 B static RAM
// (192 frames ~ 78 KB).
//
// A frame holds the values of up to 48 registers by position. The register names
// come from the meter profile that was active when it was captured, so a frame
// carries that profile's generation and is dropped if a different profile has since
// taken over (see profile_generation()).
#include <stdbool.h>
#include <stdint.h>
#include "osos_codec.h"

typedef struct {
    int64_t  epoch;       // seconds since Unix epoch at capture time
    uint32_t seq;
    uint32_t generation;  // profile_generation() when captured
    uint64_t ok_mask;     // bit i set = register i of the profile read ok
    bool     meter_ok;    // at least one register answered
    double   vals[OSOS_MAX_REGS];
} telem_frame_t;

#define TELEM_BUF_CAP CONFIG_OSOS_BUFFER_FRAMES

// Single-consumer/single-producer from the telemetry task only - no locking.
void buf_push(const telem_frame_t *f);  // drops the oldest frame when full
bool buf_pop(telem_frame_t *f);         // oldest first; false when empty
int  buf_count(void);
void buf_clear(void);                   // the profile changed: queued frames no longer fit it
