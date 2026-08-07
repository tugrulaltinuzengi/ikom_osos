"""Self-contained Modbus RTU client for the DKM-440 on COM13.

This module is the ONLY place that talks to the serial port, so the rest of the
mapping tool never has to care about pymodbus version quirks. It gives you:

  * DKM.read_window(start, count)  -> {addr: value}  (a whole block in one call,
    chunked under the 125-register Modbus limit, tolerant of dead sub-ranges)
  * DKM.read(start, count)         -> [values]       (a single small block)
  * DKM.write(start, values)       -> None           (FC16 write, e.g. set clock)

Serial settings are fixed to what this DKM-440 uses (proven with QModMaster and
the earlier pc_bridge captures): 19200 baud, 8 data bits, No parity, 1 stop bit
(8N1), slave/device id 1.

pymodbus renamed the slave keyword across releases (`slave` -> `device_id`) and
made count/id keyword-only in 3.x. `_read` / `_write` try each spelling so this
works on pymodbus 3.6 through 3.13+ without edits.
"""

from __future__ import annotations

import time

PORT_DEFAULT = "COM13"
BAUD_DEFAULT = 19200
SLAVE_DEFAULT = 1
MODBUS_MAX_REGS = 125          # a single FC03 request can return at most 125 registers

# Write-only command block (16385..16406): reading it just hangs, so wide scans skip
# it by default. Half-open ranges (lo, hi): lo <= addr < hi.
CMD_AREAS = ((16385, 16406),)


class DKM:
    """Thin, version-proof wrapper around a pymodbus serial client."""

    def __init__(self, port=PORT_DEFAULT, baud=BAUD_DEFAULT, slave=SLAVE_DEFAULT,
                 timeout=1.0, retries=0):
        self.port = port
        self.baud = baud
        self.slave = slave
        self.timeout = timeout
        self.retries = retries
        self._client = None

    # -- lifecycle -----------------------------------------------------------
    def connect(self):
        from pymodbus.client import ModbusSerialClient
        self._client = ModbusSerialClient(
            port=self.port, baudrate=self.baud, bytesize=8, parity="N", stopbits=1,
            timeout=self.timeout, retries=self.retries,
        )
        if not self._client.connect():
            raise SystemExit(
                f"ERROR: could not open {self.port}.\n"
                f"  - Is the USB-RS485 (CH340) adapter plugged in?\n"
                f"  - Close QModMaster / any other program first: the COM port is "
                f"exclusive, only one master can own it at a time."
            )
        return self

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- low-level, version-proof primitives ---------------------------------
    def _read(self, address, count):
        """One FC03 read. Returns a list of ints, or None on error/no-response."""
        fn = self._client.read_holding_registers
        rr = None
        for kwargs in ({"count": count, "device_id": self.slave},  # pymodbus >= 3.7
                       {"count": count, "slave": self.slave},       # pymodbus 3.6
                       {"count": count, "unit": self.slave}):       # very old 3.x
            try:
                rr = fn(address, **kwargs)
                break
            except TypeError:
                continue
        else:
            try:
                rr = fn(address, count, self.slave)                 # positional last resort
            except Exception:
                return None
        if rr is None or rr.isError():
            return None
        return list(rr.registers)

    def _write(self, address, values):
        """One FC16 write of a list of ints. Raises RuntimeError on failure."""
        fn = self._client.write_registers
        vals = list(values)
        rr = None
        for kwargs in ({"device_id": self.slave}, {"slave": self.slave}, {"unit": self.slave}):
            try:
                rr = fn(address, vals, **kwargs)
                break
            except TypeError:
                continue
        else:
            rr = fn(address, vals, self.slave)
        if rr is None or rr.isError():
            raise RuntimeError(f"Modbus write to {address} failed: {rr}")

    # -- convenience reads ---------------------------------------------------
    def read(self, start, count):
        """Read a single small block (count <= 125). Returns list or raises."""
        if count > MODBUS_MAX_REGS:
            raise ValueError(f"read() count {count} > {MODBUS_MAX_REGS}; use read_window()")
        vals = self._read(start, count)
        if vals is None:
            raise RuntimeError(f"Modbus read error at {start}..{start + count - 1}")
        return vals

    def _reconnect(self):
        """Hard-reset the serial session. A timeout can leave a late half-frame in
        the buffer that corrupts every later exchange; closing and reopening clears
        it. (This is what saved the earlier full-map census from cascading failures.)"""
        try:
            self._client.close()
        except Exception:
            pass
        time.sleep(0.3)
        self._client.connect()

    def read_window(self, start, count, chunk=100, gap_sleep=0.02, recover=False,
                    skip=CMD_AREAS):
        """Read [start, start+count) into {addr: value}, chunked and fault-tolerant.

        The window is walked in `chunk`-sized bites (kept under the 125 limit). A
        sub-range the device refuses (exception / timeout) is simply skipped, so a
        dead patch in the middle of the window can't abort the whole read. Returns
        only the addresses that answered.

        `skip`    : list of (lo, hi) half-open ranges never to read — defaults to the
                    write-only command block (16385..16406) whose reads just hang.
        `recover` : on a failed chunk, reset the serial session and retry once. Turn
                    this ON for WIDE scans that cross dead zones, so one timeout
                    doesn't poison the rest of the sweep. (Costs ~0.3 s per recovery.)
        """
        out = {}
        a = start
        end = start + count
        while a < end:
            in_skip = next(((lo, hi) for lo, hi in skip if lo <= a < hi), None)
            if in_skip:
                a = min(in_skip[1], end)          # jump past the skip range
                continue
            n = min(chunk, end - a)
            nxt = min((lo for lo, hi in skip if a < lo < a + n), default=None)
            if nxt is not None:
                n = nxt - a                        # stop the chunk at the skip boundary
            vals = self._read(a, n)
            if vals is None and recover:
                self._reconnect()
                vals = self._read(a, n)            # one clean retry after reset
            if vals is not None:
                for k, v in enumerate(vals):
                    out[a + k] = v
            a += n
            if gap_sleep:
                time.sleep(gap_sleep)   # politeness gap; the 440 tarpits a hammering master
        return out

    def snapshot(self, start, count, chunk=100):
        """Like read_window but also returns the wall-clock time of the read.

        Returns (values_dict, t) where t = time.time() taken right after the read.
        Used by the watch/correlate modes that need to line values up against time.
        """
        vals = self.read_window(start, count, chunk=chunk)
        return vals, time.time()


# ---------------------------------------------------------------------------
# Tiny value-interpretation helpers (no device needed) — shared by the tools.
# ---------------------------------------------------------------------------
def as_signed16(v):
    return v - 0x10000 if v >= 0x8000 else v


def combine32(hi, lo, signed=False):
    """Join two 16-bit registers into one 32-bit int (hi word at lower address)."""
    val = (hi << 16) | lo
    if signed and val >= 0x80000000:
        val -= 0x100000000
    return val


NICE_SCALES = (1, 10, 100, 1000)


def nearest_nice_scale(m):
    """Snap a fitted raw-per-volt slope to the closest documented scale (1/10/100/1000)."""
    return min(NICE_SCALES, key=lambda s: abs(m - s))
