// RAM ring buffer for offline telemetry (SRS FW-8). Only the telemetry task
// touches it, so plain indices are enough — keep it that way.
#include "buffer.h"

static telem_frame_t s_ring[TELEM_BUF_CAP];
static int s_head = 0;   // next write slot
static int s_count = 0;

void buf_push(const telem_frame_t *f)
{
    s_ring[s_head] = *f;
    s_head = (s_head + 1) % TELEM_BUF_CAP;
    if (s_count < TELEM_BUF_CAP) {
        s_count++;
    }
    // when full the write above overwrote the oldest frame — count stays capped
}

bool buf_pop(telem_frame_t *f)
{
    if (s_count == 0) {
        return false;
    }
    int tail = (s_head - s_count + TELEM_BUF_CAP) % TELEM_BUF_CAP;
    *f = s_ring[tail];
    s_count--;
    return true;
}

int buf_count(void)
{
    return s_count;
}
