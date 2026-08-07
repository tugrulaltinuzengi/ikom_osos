#pragma once
#include <stdbool.h>

// One entry per value in modbus/dkm_440_analyze/map.py MODBUS_MAP.
// All are float32 over 2 holding registers, FC03, word order "big"
// (high word first), 0-based PDU addresses.
typedef struct {
    const char *name;
    int addr;
} meter_reg_t;

#define METER_NUM_REGS 22
extern const meter_reg_t METER_REGS[METER_NUM_REGS];

void meter_init(void);
// Reads every register into vals[]; ok[i]=false marks a failed read (value
// undefined). Returns true if at least one register answered.
bool meter_read_all(float vals[METER_NUM_REGS], bool ok[METER_NUM_REGS]);
