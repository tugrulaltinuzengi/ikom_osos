#!/usr/bin/env python3
"""Copy firmware-common/*.h into the ESP8266 sketch folder.

Arduino builds copy the sketch folder, so a sketch cannot #include "../..". The
canonical files live in firmware-common/ (ESP-IDF includes them directly); this
keeps the sketch copies identical.

    python source/tools/sync_firmware_common.py          # copy
    python source/tools/sync_firmware_common.py --check  # fail on drift (CI)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMMON = os.path.join(HERE, "..", "firmware-common")
SKETCH = os.path.join(HERE, "..", "firmware-esp8266", "osos_gw8266")
FILES = ["osos_codec.h", "osos_builtin_dkm440.h"]
BANNER = ("// SYNCED COPY of firmware-common/{name} - edit that file, then run\n"
          "// python source/tools/sync_firmware_common.py\n")


def wanted(name):
    with open(os.path.join(COMMON, name), encoding="utf-8", newline="") as f:
        return BANNER.format(name=name) + f.read()


if __name__ == "__main__":
    bad = []
    for name in FILES:
        dst = os.path.join(SKETCH, name)
        text = wanted(name)
        if "--check" in sys.argv:
            cur = open(dst, encoding="utf-8", newline="").read() if os.path.exists(dst) else ""
            if cur != text:
                bad.append(name)
        else:
            with open(dst, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            print("synced", name)
    if bad:
        sys.exit("out of sync with firmware-common: " + ", ".join(bad)
                 + " - run python source/tools/sync_firmware_common.py")
