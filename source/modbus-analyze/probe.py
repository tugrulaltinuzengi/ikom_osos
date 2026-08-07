"""
DKM-440 comms probe -- find the serial settings the analyzer actually answers on.

The graph reader shows "no device" because the unit is staying SILENT to the
Modbus request (a timeout), not because of a wrong register address. A wrong
address would come back as an error reply, not silence. Silence == the request
never reached a listening slave: usually a slave-ID mismatch, a baud/parity
mismatch, or swapped RS-485 A/B lines.

This sweeps slave-id / baud / parity and reads the SUPPLY VOLTAGE register
(40260 -> PDU addr 260, float32). The first combo that replies is your setting.

Run it with the server STOPPED (Ctrl+C first) -- COM13 allows one owner at a time.
"""
from pymodbus.client import ModbusSerialClient

PORT = "COM13"
SUPPLY_ADDR = 260      # 40260 BESLEME GERILIMI (float32, 2 regs)
VL1_ADDR = 100         # 40100 ANA BARA L1 GERILIM (float32, 2 regs) -- backup probe

# Sweep order: keep the known/expected setting first, then widen out.
BAUDS = [19200, 9600, 38400, 57600, 115200]
PARITIES = ["N", "E", "O"]
UNIT_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 0]


def try_read(client, uid, addr, count=2):
    try:
        rr = client.read_holding_registers(address=addr, count=count, device_id=uid)
    except Exception as e:
        return f"EXC {type(e).__name__}"
    if rr is None:
        return "no-reply"
    if rr.isError():
        # An ERROR reply is GOOD news: the device is talking, just complaining.
        return f"REPLIED(error): {rr}"
    regs = rr.registers
    try:
        f = client.convert_from_registers(regs, data_type=client.DATATYPE.FLOAT32,
                                          word_order="big")
    except Exception:
        f = "?"
    return f"REPLIED(ok): regs={regs} float={f}"


def main():
    print(f"Probing {PORT} for the DKM-440 (reading supply voltage 40260)...\n")
    found = False
    for baud in BAUDS:
        for parity in PARITIES:
            client = ModbusSerialClient(port=PORT, baudrate=baud, parity=parity,
                                        stopbits=1, bytesize=8, timeout=0.6, retries=0)
            if not client.connect():
                print(f"[{baud} 8{parity}1] cannot open {PORT} "
                      f"(is the server or QModMaster still holding it?)")
                return
            hits = []
            for uid in UNIT_IDS:
                res = try_read(client, uid, SUPPLY_ADDR)
                if "REPLIED" in res:
                    hits.append((uid, SUPPLY_ADDR, res))
                    continue
                # supply reg silent? try the L1 voltage reg at same uid before moving on
                res2 = try_read(client, uid, VL1_ADDR)
                if "REPLIED" in res2:
                    hits.append((uid, VL1_ADDR, res2))
            client.close()
            tag = f"[{baud} 8{parity}1]"
            if hits:
                found = True
                for uid, addr, res in hits:
                    print(f"{tag}  *** DEVICE ANSWERS ***  slave_id={uid} addr={addr}  {res}")
            else:
                print(f"{tag}  silent on all slave ids {UNIT_IDS}")
    print()
    if found:
        print("Use the slave_id / baud / parity above. If addr=100 answered but 260"
              " didn't, the supply-voltage register just isn't populated -- the map is"
              " still fine for the voltages that replied.")
    else:
        print("Nothing answered on any combo. That points at PHYSICAL comms, not"
              " software:\n"
              "  - RS-485 A/B (D+/D-) may be swapped -> try swapping the two data wires\n"
              "  - is the adapter on the DKM-440's RS-485/Modbus terminals (not a\n"
              "    different port)?\n"
              "  - check the analyzer's menu: Modbus enabled, address, and baud\n"
              "  - confirm the analyzer is powered")


if __name__ == "__main__":
    main()
