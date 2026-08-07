import time

from pymodbus.client import ModbusSerialClient

# Word/register order for multi-register (32-bit) values.
# If floats read back as garbage/swapped, flip this to "little".
WORD_ORDER = "big"

# The DKM-440 tarpits a "hammering" master: fire requests back-to-back and it
# stops answering after the first one or two. Leave a short gap between reads and
# retry a dropped read once. These two knobs are what make the poll reliable.
READ_GAP = 0.03   # seconds to wait between consecutive register reads
READ_RETRIES = 1  # extra attempts if a read drops (no response / IO error)

# 1. DKM-440 register map -- TEDAS MLZ/2017-063, Cizelge 2 "Elektriksel Parametreler"
# (printed page 22 of the datasheet). Each value is a 32-bit IEEE-754 float spanning
# 2 holding registers, multiplier x1, read-only, read with Function Code 03.
#
# "address" is the 0-based PDU/wire address == documented 4xxxx register minus 40000.
# This is exactly the number you type into QModMaster's "Start Address" field.
MODBUS_MAP = {
    # --- Supply (not ANA BARA, kept for reference) ---
    "Supply_Voltage":     {"address": 260, "size": 2, "type": "float"},  # doc 40260 BESLEME GERILIMI

    # --- ANA BARA (Main Bus) voltages -- Gerilim RMS ---
    "MainBus_Voltage_L1": {"address": 100, "size": 2, "type": "float"},  # doc 40100 ANA BARA L1 GERILIM
    "MainBus_Voltage_L2": {"address": 102, "size": 2, "type": "float"},  # doc 40102 ANA BARA L2 GERILIM
    "MainBus_Voltage_L3": {"address": 104, "size": 2, "type": "float"},  # doc 40104 ANA BARA L3 GERILIM
    "MainBus_Voltage_N":  {"address": 106, "size": 2, "type": "float"},  # doc 40106 ANA BARA NOTR GERILIM

    # --- ANA BARA currents -- Akim RMS ---
    "MainBus_Current_L1": {"address": 180, "size": 2, "type": "float"},  # doc 40180 ANA BARA L1 AKIMI
    "MainBus_Current_L2": {"address": 182, "size": 2, "type": "float"},  # doc 40182 ANA BARA L2 AKIMI
    "MainBus_Current_L3": {"address": 184, "size": 2, "type": "float"},  # doc 40184 ANA BARA L3 AKIMI
    "MainBus_Current_N":  {"address": 258, "size": 2, "type": "float"},  # doc 40258 ANA BARA NOTR AKIMI

    # --- ANA BARA frequency ---
    "MainBus_Freq_L1":    {"address": 266, "size": 2, "type": "float"},  # doc 40266 ANA BARA L1 FREKANS
    "MainBus_Freq_L2":    {"address": 268, "size": 2, "type": "float"},  # doc 40268 ANA BARA L2 FREKANS
    "MainBus_Freq_L3":    {"address": 270, "size": 2, "type": "float"},  # doc 40270 ANA BARA L3 FREKANS

    # --- ANA BARA power factor -- Guc Faktoru (labels are unlabeled "-" in the PDF
    #     table body; confirmed via row-number cross-reference, rows 87/88/89) ---
    "MainBus_PF_L1":      {"address": 272, "size": 2, "type": "float"},  # doc 40272 ANA BARA L1 GUC FAKTORU
    "MainBus_PF_L2":      {"address": 274, "size": 2, "type": "float"},  # doc 40274 ANA BARA L2 GUC FAKTORU
    "MainBus_PF_L3":      {"address": 276, "size": 2, "type": "float"},  # doc 40276 ANA BARA L3 GUC FAKTORU

    # --- ANA BARA cos(phi) ---
    "MainBus_CosPhi_L1":  {"address": 350, "size": 2, "type": "float"},  # doc 40350 ANA BARA L1 COS Fi
    "MainBus_CosPhi_L2":  {"address": 352, "size": 2, "type": "float"},  # doc 40352 ANA BARA L2 COS Fi
    "MainBus_CosPhi_L3":  {"address": 354, "size": 2, "type": "float"},  # doc 40354 ANA BARA L3 COS Fi

    # --- ANA BARA tan(phi) ---
    "MainBus_TanPhi_Tot": {"address": 428, "size": 2, "type": "float"},  # doc 40428 ANA BARA TAN Fi (3-phase)
    "MainBus_TanPhi_L1":  {"address": 430, "size": 2, "type": "float"},  # doc 40430 ANA BARA L1 TAN Fi
    "MainBus_TanPhi_L2":  {"address": 432, "size": 2, "type": "float"},  # doc 40432 ANA BARA L2 TAN Fi
    "MainBus_TanPhi_L3":  {"address": 434, "size": 2, "type": "float"},  # doc 40434 ANA BARA L3 TAN Fi
}

def _read_one(client, info, unit_id):
    """Read + decode a single register. Returns a value or None, never raises.

    Retries a dropped read (the 440 sometimes ignores the first request after a
    quiet spell). A raised ModbusIOException is treated the same as an error reply.
    """
    for attempt in range(READ_RETRIES + 1):
        try:
            response = client.read_holding_registers(
                address=info["address"], count=info["size"], device_id=unit_id
            )
        except Exception:
            response = None
        if response is not None and not response.isError():
            dtype = (
                client.DATATYPE.FLOAT32
                if info["type"] == "float"
                else client.DATATYPE.INT32
            )
            return client.convert_from_registers(
                response.registers, data_type=dtype, word_order=WORD_ORDER
            )
        if attempt < READ_RETRIES:
            time.sleep(READ_GAP)  # let the line settle before retrying
    return None


def read_analyzer_data(client, unit_id):
    # Addresses in MODBUS_MAP are already 0-based PDU addresses (documented 4xxxx
    # register minus 40000), i.e. exactly what you type into QModMaster.
    results = {}
    for param_name, info in MODBUS_MAP.items():
        results[param_name] = _read_one(client, info, unit_id)
        time.sleep(READ_GAP)  # politeness gap so the 440 doesn't tarpit us
    return results

# 2. Main Execution Block
if __name__ == "__main__":
    # Setup the Serial Client as specified by the device settings
    # DKM-440: 19200 bps, 8 data bits, no parity, 1 stop bit (COM13)
    client = ModbusSerialClient(
        port='COM13', # Change to your COM port
        baudrate=19200,
        parity='N',
        stopbits=1,
        bytesize=8,
        timeout=1,
        retries=0,  # a dropped read fails fast; _read_one does its own paced retry
    )
    
    if client.connect():
        print("Connected to Modbus Analyzer Network.")
        
        # Assuming Analyzer Access ID / Slave Address is 1
        device_id = 1 
        data = read_analyzer_data(client, device_id)
        
        print("\n--- Measured Values ---")
        for key, value in data.items():
            print(f"{key}: {value:.2f}" if value is not None else f"{key}: Error")
            
        client.close()
    else:
        print("Failed to connect to the serial port.")