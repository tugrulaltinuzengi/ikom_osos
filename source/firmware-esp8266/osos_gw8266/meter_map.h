// DKM-440 register map - generated from the single source of truth at
// modbus/dkm_440_analyze/map.py (TEDAS MLZ/2017-063, Cizelge 2).
//
// Every value is a 32-bit IEEE-754 float spanning 2 holding registers, read with
// function code 03, big-endian word order. "address" is the 0-based PDU address,
// i.e. the documented 4xxxx register minus 40000.
//
// Key names are copied verbatim from map.py because the phone app and the SRS-01
// telemetry contract both key off these exact strings. Do not "tidy" them.
//
// C-4: the 16385-16406 command block is write-only and unverified. It is absent
// from this table on purpose. Never add it.
#pragma once

#include <stdint.h>

struct MeterReg {
  const char* key;
  uint16_t address;
};

// The DKM-440 stops answering a master that fires requests back to back. This gap
// is a property of the device, not the transport, so it survived the move to TCP.
static const uint16_t kReadGapMs = 30;

static const MeterReg kMeterRegs[] = {
    // Supply rail (not ANA BARA) - this is "besleme gerilimi"
    {"Supply_Voltage",     260},

    // ANA BARA voltages - Gerilim RMS
    {"MainBus_Voltage_L1", 100},
    {"MainBus_Voltage_L2", 102},
    {"MainBus_Voltage_L3", 104},
    {"MainBus_Voltage_N",  106},

    // ANA BARA currents - Akim RMS
    {"MainBus_Current_L1", 180},
    {"MainBus_Current_L2", 182},
    {"MainBus_Current_L3", 184},
    {"MainBus_Current_N",  258},

    // ANA BARA frequency
    {"MainBus_Freq_L1",    266},
    {"MainBus_Freq_L2",    268},
    {"MainBus_Freq_L3",    270},

    // ANA BARA power factor
    {"MainBus_PF_L1",      272},
    {"MainBus_PF_L2",      274},
    {"MainBus_PF_L3",      276},

    // ANA BARA cos(phi)
    {"MainBus_CosPhi_L1",  350},
    {"MainBus_CosPhi_L2",  352},
    {"MainBus_CosPhi_L3",  354},

    // ANA BARA tan(phi)
    {"MainBus_TanPhi_Tot", 428},
    {"MainBus_TanPhi_L1",  430},
    {"MainBus_TanPhi_L2",  432},
    {"MainBus_TanPhi_L3",  434},
};

static const uint8_t kMeterRegCount = sizeof(kMeterRegs) / sizeof(kMeterRegs[0]);
