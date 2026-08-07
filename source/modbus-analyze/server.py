"""
Really-simple live graph reader for the DKM-440.

Runs a tiny HTTP server that:
  * polls every register in map.MODBUS_MAP over Modbus RTU in a background thread,
  * caches the latest values,
  * serves index.html and a /data JSON endpoint (same origin, so the browser
    can fetch it with no external libraries / no CORS fuss).

Open http://localhost:8000 in Chrome/Edge/Firefox and every value is graphed.

The serial device does NOT need to be connected to see the UI -- if the port
can't be opened the page still loads and shows "disconnected" with empty plots,
and the server keeps retrying the connection.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pymodbus.client import ModbusSerialClient

from map import MODBUS_MAP, read_analyzer_data

# ----------------------------------------------------------------------------
# Config -- matches map.py (DKM-440: 19200 8N1 on COM13, slave/unit id 1)
# ----------------------------------------------------------------------------
SERIAL_PORT = "COM13"
BAUDRATE = 19200
UNIT_ID = 1
HTTP_PORT = 8000
POLL_PERIOD = 0.5  # seconds between device polls

HERE = Path(__file__).resolve().parent

# Shared state written by the poller, read by the HTTP handler.
_state_lock = threading.Lock()
_state = {
    "ts": 0.0,          # epoch seconds of last successful/attempted read
    "connected": False,
    "values": {name: None for name in MODBUS_MAP},
}


def _unit_for(name: str) -> str:
    """Best-effort engineering unit, inferred from the register key name."""
    n = name.lower()
    if "voltage" in n:
        return "V"
    if "current" in n:
        return "A"
    if "freq" in n:
        return "Hz"
    return ""  # power factor / cos / tan are unitless


UNITS = {name: _unit_for(name) for name in MODBUS_MAP}


def poller():
    """Background loop: keep a Modbus client connected and refresh _state."""
    client = ModbusSerialClient(
        port=SERIAL_PORT,
        baudrate=BAUDRATE,
        parity="N",
        stopbits=1,
        bytesize=8,
        timeout=1,
        retries=0,  # a miss fails fast; map.read_analyzer_data does its own paced retry
    )
    connected = False
    while True:
        t0 = time.time()
        try:
            if not connected:
                connected = client.connect()
            if connected:
                values = read_analyzer_data(client, UNIT_ID)  # paced + retrying
                # If every read failed, treat the link as down and retry a reconnect.
                if all(v is None for v in values.values()):
                    connected = False
                    client.close()
            else:
                values = {name: None for name in MODBUS_MAP}
        except Exception:
            connected = False
            try:
                client.close()
            except Exception:
                pass
            values = {name: None for name in MODBUS_MAP}

        with _state_lock:
            _state["ts"] = time.time()
            _state["connected"] = connected
            _state["values"] = values

        # Sleep the remainder of the poll period.
        time.sleep(max(0.0, POLL_PERIOD - (time.time() - t0)))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (HERE / "index.html").read_text(encoding="utf-8")
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path.startswith("/data"):
            with _state_lock:
                snapshot = {
                    "ts": _state["ts"],
                    "connected": _state["connected"],
                    "order": list(MODBUS_MAP.keys()),
                    "units": UNITS,
                    "values": _state["values"],
                    "meta": {
                        "port": SERIAL_PORT,
                        "baud": BAUDRATE,
                        "unit": UNIT_ID,
                    },
                }
            self._send(200, json.dumps(snapshot), "application/json")
        else:
            self._send(404, "not found", "text/plain")

    def log_message(self, *args):  # silence per-request console spam
        pass


def main():
    threading.Thread(target=poller, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    print(f"DKM-440 graph reader -> http://localhost:{HTTP_PORT}")
    print(f"Serial: {SERIAL_PORT} @ {BAUDRATE} 8N1, unit id {UNIT_ID}")
    print("Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
