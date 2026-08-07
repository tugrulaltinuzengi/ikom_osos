import csv
import time

from dkm_modbus import DKM

# -----------------------------
# Configuration
# -----------------------------

START_REGISTER = 0
REGISTER_COUNT = 25000       # scan 0..24999
DURATION = 60                # seconds
CHUNK = 100                  # don't change (>125 is illegal)
OUTPUT = "scan_data.csv"

# -----------------------------

print("Connecting...")

dev = DKM().connect()

print("Connected.")
print()
print("========================================")
print("60 second recording begins NOW")
print()
print("Change your voltage like this:")
print()
print(" 0-5 s   : 90 V")
print(" 5-10 s  : 60 V")
print("10-15 s  : 30 V")
print("15-20 s  : 90 V")
print("20-25 s  : 60 V")
print("25-30 s  : 30 V")
print("30-35 s  : 90 V")
print("35-40 s  : 60 V")
print("40-45 s  : 30 V")
print("45-50 s  : 90 V")
print("50-55 s  : 60 V")
print("55-60 s  : 30 V")
print("========================================")
print()

end_time = time.time() + DURATION

scan_number = 0

with open(OUTPUT, "w", newline="") as f:

    writer = csv.writer(f)

    first = True

    while time.time() < end_time:

        timestamp = time.time()

        regs = dev.read_window(
            START_REGISTER,
            REGISTER_COUNT,
            chunk=CHUNK,
            recover=True
        )

        if first:

            addresses = sorted(regs.keys())

            writer.writerow(
                ["time"] +
                [str(a) for a in addresses]
            )

            first = False

        row = [timestamp]

        for a in addresses:
            row.append(regs.get(a, ""))

        writer.writerow(row)

        scan_number += 1

        elapsed = DURATION - (end_time - time.time())

        print(
            f"\rScan {scan_number:4d} | "
            f"{elapsed:5.1f}/{DURATION}s | "
            f"{len(addresses)} registers",
            end=""
        )

print("\n\nFinished.")

dev.close()

print(f"Saved to {OUTPUT}")