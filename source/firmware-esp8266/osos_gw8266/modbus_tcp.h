// Minimal Modbus TCP client (function codes 03 and 04).
//
// Modbus TCP is Modbus RTU with the serial framing replaced by a 7-byte MBAP
// header, and with error detection delegated to TCP. There is no CRC and no
// inter-frame timing to honour, which is why this file is ~100 lines while the
// RS-485 RTU path needed a whole component.
//
//   MBAP:  [txn hi][txn lo][proto hi][proto lo][len hi][len lo][unit]
//   PDU :  [func][addr hi][addr lo][qty hi][qty lo]           (function 03 or 04)
//
// Some meters (the DKM-440 among them) tarpit a master that fires requests back
// to back, so callers keep a gap between reads: the profile's timing.read_gap_ms.
// That is a device limitation, not a transport one - it survives the move to TCP.
// Register decoding is not done here; see osos_codec.h.
#pragma once

#include <ESP8266WiFi.h>
#include <string.h>

class ModbusTcp {
 public:
  void configure(const char* host, uint16_t port, uint8_t unit_id) {
    // One socket serves one endpoint. Pointing at another meter must drop the
    // connection, or the next read would go to the previous meter's socket.
    if (client_.connected() && (host_ == nullptr || strcmp(host_, host) != 0 || port_ != port)) {
      client_.stop();
    }
    host_ = host;
    port_ = port;
    unit_id_ = unit_id;
  }

  bool connected() { return client_.connected(); }

  bool connect() {
    if (client_.connected()) return true;
    client_.setTimeout(timeout_ms_);
    if (!client_.connect(host_, port_)) return false;
    client_.setNoDelay(true);  // Modbus is request/response; Nagle only adds latency
    return true;
  }

  void stop() { client_.stop(); }

  // Per-request timeout, taken from the profile. Keep it short: a dead meter must
  // not block the loop long enough to lose the MQTT keepalive.
  void setTimeoutMs(uint16_t ms) { timeout_ms_ = ms; client_.setTimeout(ms); }

  // Reads `qty` holding registers (function 03) into `out`.
  bool readHolding(uint16_t addr, uint16_t qty, uint16_t* out) { return readRegisters(0x03, addr, qty, out); }

  // Reads `qty` registers with function 03 (holding) or 04 (input) into `out`.
  // Returns false on any transport error or protocol exception.
  bool readRegisters(uint8_t fc, uint16_t addr, uint16_t qty, uint16_t* out) {
    if ((fc != 0x03 && fc != 0x04) || qty < 1 || qty > 125) return false;
    if (!connect()) return false;

    const uint16_t txn = ++txn_id_;
    uint8_t req[12];
    req[0] = txn >> 8;   req[1] = txn & 0xFF;
    req[2] = 0;          req[3] = 0;          // protocol id 0 == Modbus
    req[4] = 0;          req[5] = 6;          // length: unit + 5 PDU bytes
    req[6] = unit_id_;
    req[7] = fc;                              // 03 holding / 04 input registers
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
    if (hdr[7] != fc) { stop(); return false; }

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

  uint8_t lastException() const { return last_exception_; }

 private:
  bool readFully(uint8_t* dst, size_t n) {
    const uint32_t deadline = millis() + timeout_ms_;
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
  // gateway dropped by the broker. The default stays short; profiles may raise it
  // (timing.timeout_ms), and the poll loop gives up early regardless.
  uint16_t timeout_ms_ = 500;

  WiFiClient client_;
  const char* host_ = nullptr;
  uint16_t port_ = 502;
  uint8_t unit_id_ = 1;
  uint16_t txn_id_ = 0;
  uint8_t last_exception_ = 0;
};
