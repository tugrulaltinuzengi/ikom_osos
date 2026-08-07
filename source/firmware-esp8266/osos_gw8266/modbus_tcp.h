// Minimal Modbus TCP client for the DKM-440.
//
// Modbus TCP is Modbus RTU with the serial framing replaced by a 7-byte MBAP
// header, and with error detection delegated to TCP. There is no CRC and no
// inter-frame timing to honour, which is why this file is ~100 lines while the
// RS-485 RTU path needed a whole component.
//
//   MBAP:  [txn hi][txn lo][proto hi][proto lo][len hi][len lo][unit]
//   PDU :  [func][addr hi][addr lo][qty hi][qty lo]           (function 03)
//
// The DKM-440 still tarpits a master that fires requests back to back, so
// callers must keep a gap between reads (see kReadGapMs in meter_map.h). That
// is a device limitation, not a transport one - it survives the move to TCP.
#pragma once

#include <ESP8266WiFi.h>

class ModbusTcp {
 public:
  void configure(const char* host, uint16_t port, uint8_t unit_id) {
    host_ = host;
    port_ = port;
    unit_id_ = unit_id;
  }

  bool connected() { return client_.connected(); }

  bool connect() {
    if (client_.connected()) return true;
    client_.setTimeout(kTimeoutMs);
    if (!client_.connect(host_, port_)) return false;
    client_.setNoDelay(true);  // Modbus is request/response; Nagle only adds latency
    return true;
  }

  void stop() { client_.stop(); }

  // Reads `qty` holding registers (function 03) into `out`.
  // Returns false on any transport error or protocol exception.
  bool readHolding(uint16_t addr, uint16_t qty, uint16_t* out) {
    if (!connect()) return false;

    const uint16_t txn = ++txn_id_;
    uint8_t req[12];
    req[0] = txn >> 8;   req[1] = txn & 0xFF;
    req[2] = 0;          req[3] = 0;          // protocol id 0 == Modbus
    req[4] = 0;          req[5] = 6;          // length: unit + 5 PDU bytes
    req[6] = unit_id_;
    req[7] = 0x03;                            // read holding registers
    req[8] = addr >> 8;  req[9] = addr & 0xFF;
    req[10] = qty >> 8;  req[11] = qty & 0xFF;

    if (client_.write(req, sizeof req) != sizeof req) { stop(); return false; }

    uint8_t hdr[9];
    if (!readFully(hdr, sizeof hdr)) { stop(); return false; }

    // Echoed transaction id guards against a stale reply from a previous timeout.
    if (((hdr[0] << 8) | hdr[1]) != txn) { stop(); return false; }

    if (hdr[7] & 0x80) {            // exception response: function | 0x80
      uint8_t code;
      readFully(&code, 1);
      last_exception_ = code;
      return false;
    }
    if (hdr[7] != 0x03) { stop(); return false; }

    const uint8_t byte_count = hdr[8];
    if (byte_count != qty * 2) { stop(); return false; }

    for (uint16_t i = 0; i < qty; i++) {
      uint8_t pair[2];
      if (!readFully(pair, 2)) { stop(); return false; }
      out[i] = (uint16_t(pair[0]) << 8) | pair[1];
    }
    last_exception_ = 0;
    return true;
  }

  // Two consecutive registers as one IEEE-754 float, big-endian word order.
  // WORD_ORDER="big" in dkm_440_analyze/map.py; verified against a live read
  // (0x41D4 0000 -> 26.5 V supply).
  bool readFloatBE(uint16_t addr, float* out) {
    uint16_t regs[2];
    if (!readHolding(addr, 2, regs)) return false;
    const uint32_t bits = (uint32_t(regs[0]) << 16) | regs[1];
    float value;
    memcpy(&value, &bits, sizeof value);   // type-pun without UB
    if (isnan(value) || isinf(value)) return false;  // corrupt-but-valid frame
    *out = value;
    return true;
  }

  uint8_t lastException() const { return last_exception_; }

 private:
  bool readFully(uint8_t* dst, size_t n) {
    const uint32_t deadline = millis() + kTimeoutMs;
    size_t got = 0;
    while (got < n) {
      if (millis() > deadline) return false;
      const int r = client_.read(dst + got, n - got);
      if (r > 0) got += r;
      else if (!client_.connected()) return false;
      else delay(1);
      yield();                                 // never starve the WiFi stack
    }
    return true;
  }

  // The DKM-440 answers in tens of milliseconds over TCP. A long timeout only
  // matters when the meter is dead, and then it is actively harmful: 22 registers
  // x 1500 ms = 33 s of blocking, which starved the MQTT keepalive and got the
  // gateway dropped by the broker. Keep this short and let the caller give up
  // early instead.
  static const uint16_t kTimeoutMs = 500;

  WiFiClient client_;
  const char* host_ = nullptr;
  uint16_t port_ = 502;
  uint8_t unit_id_ = 1;
  uint16_t txn_id_ = 0;
  uint8_t last_exception_ = 0;
};
