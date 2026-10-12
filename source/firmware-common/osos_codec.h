// OSOS meter codec - shared by both gateway firmwares (C and C++).
//
// Everything a gateway needs to turn a meter profile into values, with no
// hardware, no Arduino and no ESP-IDF dependency, so it is compiled and tested on
// a PC against source/meter-profiles/vectors.json:
//
//   osos_decode()  16-bit register words -> number (8 types, 4 byte layouts)
//   osos_plan()    merge adjacent registers into as few Modbus requests as allowed
//   osos_poll()    read a whole profile through a caller-supplied transport
//   osos_format()  a number as published text
//
// Canonical copy. firmware-esp8266/osos_gw8266/osos_codec.h is a synced copy
// (Arduino builds copy the sketch folder, so it cannot include "../"); run
// tools/sync_firmware_common.py after editing.
//
// The reference implementation is tools/meterprofile.py. Keep them in step.
#ifndef OSOS_CODEC_H
#define OSOS_CODEC_H

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

#define OSOS_MAX_REGS 48
#define OSOS_KEY_LEN  32          /* including the terminator: keys are 1..31 chars */

enum {
  OSOS_T_U16 = 0, OSOS_T_I16 = 1,
  OSOS_T_U32 = 2, OSOS_T_I32 = 3, OSOS_T_F32 = 4,
  OSOS_T_U64 = 5, OSOS_T_I64 = 6, OSOS_T_F64 = 7,
  OSOS_T_COUNT = 8
};

#define OSOS_ORDER_WORD_LITTLE 0x01
#define OSOS_ORDER_BYTE_LITTLE 0x02

/* One register of a profile, as stored on flash and used while polling.
 * 56 bytes, naturally aligned, little-endian. tools/meterprofile.py
 * binary_record() writes exactly this layout.
 * scale/offset are doubles on purpose: a float scale of 0.001 is really
 * 0.00100000005, which turns a 1e9-count energy meter into 1000000.05 kWh. */
typedef struct {
  char     key[OSOS_KEY_LEN];
  double   scale;
  double   offset;
  uint16_t address;      /* 0-based PDU address */
  uint8_t  fc;           /* 3 or 4 */
  uint8_t  type;         /* OSOS_T_* */
  uint8_t  order;        /* OSOS_ORDER_* */
  uint8_t  decimals;     /* 0..6 */
  uint8_t  reserved[2];
} osos_reg_t;

/* Stored-profile header (64 bytes), followed by n osos_reg_t. */
#define OSOS_PF_MAGIC "OSPF"
#define OSOS_PF_VER   1
typedef struct {
  char     magic[4];
  uint8_t  ver;
  uint8_t  n;
  uint16_t rev;
  uint16_t gap_ms;
  uint16_t timeout_ms;
  uint8_t  max_block;
  uint8_t  retries;
  uint16_t blob_len;     /* bytes of display metadata stored beside this file */
  char     name[48];     /* UTF-8, at most 44 bytes used, always terminated */
} osos_pf_header_t;

/* The profile compiled into the firmware as a fallback (generated, see
 * osos_builtin_dkm440.h). regs and blob live in flash (PROGMEM on the ESP8266). */
typedef struct {
  const char*       id;
  osos_pf_header_t  hdr;
  const osos_reg_t* regs;     /* hdr.n entries */
  const char*       blob;     /* hdr.blob_len bytes, not terminated */
} osos_builtin_t;

#if !defined(ARDUINO) && !defined(PROGMEM)
#define PROGMEM
#endif

typedef char osos_reg_size_check[(sizeof(osos_reg_t) == 56) ? 1 : -1];
typedef char osos_hdr_size_check[(sizeof(osos_pf_header_t) == 64) ? 1 : -1];

static inline uint8_t osos_type_words(uint8_t type) {
  switch (type) {
    case OSOS_T_U16: case OSOS_T_I16: return 1;
    case OSOS_T_U32: case OSOS_T_I32: case OSOS_T_F32: return 2;
    case OSOS_T_U64: case OSOS_T_I64: case OSOS_T_F64: return 4;
    default: return 0;
  }
}

/* Type name <-> code, for the wire format. Returns -1 when unknown. */
static inline int osos_type_from_name(const char* s) {
  static const char* const names[OSOS_T_COUNT] = {"u16", "i16", "u32", "i32", "f32", "u64", "i64", "f64"};
  if (!s) return -1;
  for (int i = 0; i < OSOS_T_COUNT; i++) if (strcmp(s, names[i]) == 0) return i;
  return -1;
}

/* Decode the words of one register as read from the wire.
 * Returns false for a non-finite float (a corrupt-but-valid frame), which the
 * caller treats as a failed read. */
static inline bool osos_decode(const osos_reg_t* r, const uint16_t* words, double* out) {
  const uint8_t n = osos_type_words(r->type);
  if (n == 0) return false;
  uint16_t w[4];
  for (uint8_t i = 0; i < n; i++) {
    uint16_t v = words[i];
    if (r->order & OSOS_ORDER_BYTE_LITTLE) v = (uint16_t)((v << 8) | (v >> 8));
    w[(r->order & OSOS_ORDER_WORD_LITTLE) ? (n - 1 - i) : i] = v;
  }
  uint64_t bits = 0;
  for (uint8_t i = 0; i < n; i++) bits = (bits << 16) | w[i];

  double raw;
  switch (r->type) {
    case OSOS_T_U16: case OSOS_T_U32: raw = (double)(uint32_t)bits; break;
    case OSOS_T_U64: raw = (double)bits; break;
    case OSOS_T_I16: raw = (double)(int16_t)(uint16_t)bits; break;
    case OSOS_T_I32: raw = (double)(int32_t)(uint32_t)bits; break;
    case OSOS_T_I64: raw = (double)(int64_t)bits; break;
    case OSOS_T_F32: {
      const uint32_t b32 = (uint32_t)bits;
      float f;
      memcpy(&f, &b32, sizeof f);          /* type-pun without UB */
      raw = (double)f;
      break;
    }
    default: {                              /* OSOS_T_F64 */
      double d;
      memcpy(&d, &bits, sizeof d);
      raw = d;
      break;
    }
  }
  if (r->type == OSOS_T_F32 || r->type == OSOS_T_F64) {
    if (isnan(raw) || isinf(raw)) return false;
  }
  *out = raw * r->scale + r->offset;
  return true;
}

/* A planned Modbus request: registers order[first .. first+count) are served by
 * reading `words` registers starting at `start`. */
typedef struct {
  uint16_t start;
  uint16_t words;
  uint8_t  fc;
  uint8_t  first;
  uint8_t  count;
} osos_block_t;

/* Group registers into requests. `order` receives register indexes sorted by
 * (fc, address, index); `blocks` receives the plan. Both need room for n entries.
 * Registers merge when they share a function code and touch or overlap, while the
 * block stays within max_block words. A block is never smaller than its widest
 * register, so max_block == 1 means one request per register. Returns the block
 * count. */
static inline int osos_plan(const osos_reg_t* regs, int n, int max_block,
                            uint8_t* order, osos_block_t* blocks) {
  for (int i = 0; i < n; i++) order[i] = (uint8_t)i;
  for (int i = 1; i < n; i++) {                       /* insertion sort, n <= 48 */
    const uint8_t cur = order[i];
    int j = i - 1;
    while (j >= 0) {
      const osos_reg_t* p = &regs[order[j]];
      const osos_reg_t* c = &regs[cur];
      const bool after = (p->fc > c->fc) || (p->fc == c->fc && p->address > c->address) ||
                         (p->fc == c->fc && p->address == c->address && order[j] > cur);
      if (!after) break;
      order[j + 1] = order[j];
      j--;
    }
    order[j + 1] = cur;
  }

  int nb = 0;
  for (int k = 0; k < n; k++) {
    const osos_reg_t* r = &regs[order[k]];
    const uint32_t end = (uint32_t)r->address + osos_type_words(r->type);
    if (nb > 0) {
      osos_block_t* b = &blocks[nb - 1];
      const uint32_t bend = (uint32_t)b->start + b->words;
      const uint32_t nend = end > bend ? end : bend;
      if (b->fc == r->fc && r->address <= bend && nend - b->start <= (uint32_t)max_block) {
        b->words = (uint16_t)(nend - b->start);
        b->count++;
        continue;
      }
    }
    blocks[nb].start = r->address;
    blocks[nb].words = (uint16_t)(end - r->address);
    blocks[nb].fc = r->fc;
    blocks[nb].first = (uint8_t)k;
    blocks[nb].count = 1;
    nb++;
  }
  return nb;
}

/* Transport used by osos_poll(). read() fetches `words` registers; it returns
 * false on any failure. idle() runs after every request: the caller sleeps the
 * profile's read gap there. It returns false to abandon the sweep (a time budget,
 * so a slow meter cannot starve the MQTT keepalive); the rest then stay not-ok. */
typedef struct {
  bool (*read)(void* ctx, uint8_t fc, uint16_t start, uint16_t words, uint16_t* out);
  bool (*idle)(void* ctx, uint16_t gap_ms);
  void* ctx;
} osos_io_t;

typedef struct {
  uint16_t gap_ms;
  uint16_t timeout_ms;
  uint8_t  max_block;
  uint8_t  retries;
} osos_timing_t;

typedef struct {
  double  value[OSOS_MAX_REGS];     /* profile order */
  bool    ok[OSOS_MAX_REGS];
  uint8_t ok_count;
  bool    gave_up;
} osos_poll_result_t;

#define OSOS_GIVE_UP_AFTER 3        /* consecutive failed registers */

/* Read every register. A dead meter must not stall the gateway: after three
 * consecutive failed registers the sweep stops and the rest stay not-ok. */
static inline void osos_poll(const osos_reg_t* regs, int n, const osos_timing_t* t,
                             const osos_io_t* io, osos_poll_result_t* res) {
  uint8_t order[OSOS_MAX_REGS];
  osos_block_t blocks[OSOS_MAX_REGS];
  uint16_t words[64];
  int block_max = t->max_block < 1 ? 1 : (t->max_block > 64 ? 64 : t->max_block);
  res->ok_count = 0;
  res->gave_up = false;
  for (int i = 0; i < n; i++) { res->ok[i] = false; res->value[i] = 0; }

  const int nb = osos_plan(regs, n, block_max, order, blocks);
  int fails = 0;
  for (int bi = 0; bi < nb; bi++) {
    const osos_block_t* b = &blocks[bi];
    bool got = false;
    for (int attempt = 0; attempt <= t->retries && !got; attempt++) {
      got = io->read(io->ctx, b->fc, b->start, b->words, words);
    }
    for (int k = 0; k < b->count; k++) {
      const int idx = order[b->first + k];
      const osos_reg_t* r = &regs[idx];
      double v;
      if (got && osos_decode(r, words + (r->address - b->start), &v)) {
        res->value[idx] = v;
        res->ok[idx] = true;
        res->ok_count++;
        fails = 0;
      } else {
        fails++;
      }
    }
    const bool more = io->idle ? io->idle(io->ctx, t->gap_ms) : true;
    if (fails >= OSOS_GIVE_UP_AFTER || !more) { res->gave_up = true; break; }
  }
}

/* "%.*f" without printf's float support dependency on Arduino. */
#if defined(ARDUINO)
#  include <stdlib.h>
static inline void osos_format(double v, int decimals, char* out, size_t n) {
  if (n < 2) return;
  dtostrf(v, 1, decimals, out);
  out[n - 1] = '\0';
}
#else
static inline void osos_format(double v, int decimals, char* out, size_t n) {
  snprintf(out, n, "%.*f", decimals, v);
}
#endif

#ifdef __cplusplus
}
#endif
#endif /* OSOS_CODEC_H */
