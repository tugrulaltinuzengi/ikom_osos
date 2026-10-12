#!/usr/bin/env python3
"""Regenerate source/meter-profiles/vectors.json.

The decode, plan and poll expectations below are written by hand (they do not
come from meterprofile.py), so the vectors check the reference implementation as
well as the ports. Only the `wire` and `records` sections are derived from it -
those pin down byte-exact output that every language must reproduce.

    python source/tools/gen_vectors.py          # rewrite the file
    python source/tools/gen_vectors.py --check  # fail if it is stale (CI)
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import meterprofile as mp  # noqa: E402

PROFILES = os.path.join(HERE, "..", "meter-profiles")
OUT = os.path.join(PROFILES, "vectors.json")


def load(name):
    return mp.load_profile(os.path.join(PROFILES, name))


def decode_cases():
    c = []

    def add(name, words, t, expect, w="big", b="big", s=1, o=0):
        c.append({"name": name, "words": words, "type": t, "word_order": w,
                  "byte_order": b, "scale": s, "offset": o, "expect": expect})

    # 26.5 == 0x41D40000, the supply-voltage reading verified on a live DKM-440
    add("f32 ABCD", [0x41D4, 0x0000], "f32", 26.5)
    add("f32 CDAB", [0x0000, 0x41D4], "f32", 26.5, w="little")
    add("f32 BADC", [0xD441, 0x0000], "f32", 26.5, b="little")
    add("f32 DCBA", [0x0000, 0xD441], "f32", 26.5, w="little", b="little")
    add("f32 negative", [0xC2B4, 0x0000], "f32", -90.0)
    add("f32 NaN is a failed read", [0x7FC0, 0x0000], "f32", None)
    add("f32 +Inf is a failed read", [0x7F80, 0x0000], "f32", None)
    add("f32 -Inf is a failed read", [0xFF80, 0x0000], "f32", None)
    add("u16", [0x1234], "u16", 4660)
    add("u16 max", [0xFFFF], "u16", 65535)
    add("i16 negative", [0xFFFE], "i16", -2)
    add("i16 min", [0x8000], "i16", -32768)
    add("i16 byte swapped", [0xFEFF], "i16", -2, b="little")
    add("u32 big", [0x0001, 0x0002], "u32", 65538)
    add("u32 little", [0x0001, 0x0002], "u32", 131073, w="little")
    add("u32 max", [0xFFFF, 0xFFFF], "u32", 4294967295)
    add("i32 negative", [0xFFFF, 0xFFFE], "i32", -2)
    add("i32 min", [0x8000, 0x0000], "i32", -2147483648)
    add("u64", [0, 0, 0x0001, 0x0000], "u64", 65536)
    add("i64 negative", [0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF], "i64", -1)
    add("f64", [0x3FF8, 0, 0, 0], "f64", 1.5)
    add("f64 little words", [0, 0, 0, 0x3FF8], "f64", 1.5, w="little")
    add("scale tenths", [2305], "u16", 230.5, s=0.1)
    add("scale and offset", [650], "i16", 25.0, s=0.1, o=-40)
    add("offset only", [100], "i16", 50, o=-50)
    add("u32 counter scaled", [0x0001, 0x86A0], "u32", 1000.0, s=0.01)
    return c


def base_profile():
    return {
        "schema": 1, "id": "t1", "name": "Test", "rev": 1,
        "registers": [
            {"key": "A", "address": 0},
            {"key": "B", "address": 2, "type": "u16", "scale": 0.1},
        ],
        "views": [{"id": "v1", "label": "One", "keys": ["A", "B"]}],
    }


def validation_cases():
    cases = []

    def case(name, mutate, errors, warns=()):
        p = base_profile()
        mutate(p)
        cases.append({"name": name, "profile": p,
                      "errors": sorted(errors), "warns": sorted(warns)})

    case("valid", lambda p: None, [])
    case("wrong schema", lambda p: p.update(schema=2), ["schema.unsupported"])
    case("bad id", lambda p: p.update(id="Bad Id"), ["id.invalid"])
    case("id too long", lambda p: p.update(id="a" * 25), ["id.invalid"])
    case("no name", lambda p: p.pop("name"), ["name.missing"])
    case("name too long", lambda p: p.update(name="x" * 49), ["name.long"])
    case("rev out of range", lambda p: p.update(rev=70000), ["rev.invalid"])
    case("transport", lambda p: p.update(transport="usb"), ["transport.invalid"])
    case("timing range", lambda p: p.update(timing={"max_block": 65}), ["timing.range"])
    case("request budget exceeded", lambda p: p.update(timing={"timeout_ms": 5000, "retries": 3}),
         ["timing.budget"])
    case("request budget at the limit", lambda p: p.update(timing={"timeout_ms": 4000, "retries": 1}), [])
    case("timing gap range", lambda p: p.update(timing={"read_gap_ms": -1}), ["timing.range"])
    case("no registers", lambda p: p.update(registers=[], views=[]), ["registers.missing"])
    case("too many registers",
         lambda p: p.update(registers=[{"key": f"R{i}", "address": i * 2} for i in range(49)],
                            views=[]),
         ["registers.toomany"])
    case("duplicate key", lambda p: (p["registers"][1].update(key="A"), p.update(views=[])),
         ["reg.key.duplicate"])
    case("bad key", lambda p: (p["registers"][0].update(key="bad key"), p.update(views=[])),
         ["reg.key.invalid"])
    case("key too long", lambda p: (p["registers"][0].update(key="k" * 32), p.update(views=[])),
         ["reg.key.invalid"])
    case("address negative", lambda p: p["registers"][0].update(address=-1), ["reg.address.range"])
    case("address too big", lambda p: p["registers"][0].update(address=65536), ["reg.address.range"])
    case("32-bit runs off the end", lambda p: p["registers"][0].update(address=65535),
         ["reg.address.range"])
    case("16-bit at the last address",
         lambda p: p["registers"][1].update(address=65535), [])
    case("address not an integer", lambda p: p["registers"][0].update(address=1.5),
         ["reg.address.range"])
    case("bad fc", lambda p: p["registers"][0].update(fc=1), ["reg.fc.invalid"])
    case("input registers", lambda p: p["registers"][0].update(fc=4), [])
    case("bad type", lambda p: p["registers"][0].update(type="f16"), ["reg.type.invalid"])
    case("bad word order", lambda p: p["registers"][0].update(word_order="mid"),
         ["reg.order.invalid"])
    case("bad default type", lambda p: p.update(defaults={"type": "x"}), ["reg.type.invalid"])
    case("scale zero", lambda p: p["registers"][1].update(scale=0), ["reg.scale.zero"])
    case("scale not a number", lambda p: p["registers"][1].update(scale="2"),
         ["reg.number.invalid"])
    case("decimals", lambda p: p["registers"][0].update(decimals=7), ["reg.decimals"])
    case("overlap", lambda p: p["registers"][1].update(address=1, type="f32"),
         [], ["reg.overlap"])
    case("same register twice is fine", lambda p: p["registers"][1].update(address=0, type="f32"),
         [])
    case("unit too long", lambda p: p["registers"][0].update(unit="123456789"), ["text.invalid"])
    case("view unknown key", lambda p: p["views"][0].update(keys=["A", "Z"]),
         ["view.keys.unknown"])
    case("view without keys", lambda p: p["views"][0].update(keys=[]), ["view.keys.missing"])
    case("duplicate view", lambda p: p["views"].append(copy.deepcopy(p["views"][0])),
         ["view.id.duplicate"])
    case("view id may be upper case", lambda p: p["views"][0].update(id="L1"), [])
    return cases


def plan_cases():
    def regs(*rows):
        return [{"address": a, "fc": f, "type": t} for a, f, t in rows]
    cases = [
        {"name": "max_block 1 never merges",
         "regs": regs((0, 3, "f32"), (2, 3, "f32"), (4, 3, "f32")), "max_block": 1,
         "blocks": [[3, 0, 2, [0]], [3, 2, 2, [1]], [3, 4, 2, [2]]]},
        {"name": "contiguous registers merge up to the limit",
         "regs": regs((0, 3, "f32"), (2, 3, "f32"), (4, 3, "f32")), "max_block": 4,
         "blocks": [[3, 0, 4, [0, 1]], [3, 4, 2, [2]]]},
        {"name": "everything fits in one request",
         "regs": regs((0, 3, "f32"), (2, 3, "f32"), (4, 3, "u16")), "max_block": 16,
         "blocks": [[3, 0, 5, [0, 1, 2]]]},
        {"name": "a gap breaks the block",
         "regs": regs((0, 3, "f32"), (4, 3, "f32")), "max_block": 16,
         "blocks": [[3, 0, 2, [0]], [3, 4, 2, [1]]]},
        {"name": "different function codes never merge",
         "regs": regs((0, 3, "f32"), (2, 4, "f32")), "max_block": 16,
         "blocks": [[3, 0, 2, [0]], [4, 2, 2, [1]]]},
        {"name": "listed out of order, planned by address",
         "regs": regs((4, 3, "u16"), (0, 3, "u16"), (1, 3, "u16")), "max_block": 8,
         "blocks": [[3, 0, 2, [1, 2]], [3, 4, 1, [0]]]},
        {"name": "overlapping registers share a request",
         "regs": regs((0, 3, "u32"), (1, 3, "u16")), "max_block": 8,
         "blocks": [[3, 0, 2, [0, 1]]]},
    ]
    return cases


def poll_cases():
    gi = "examples/generic-int-scaled.json"
    mem_ok = {"0": 2305, "1": 1234, "2": 0xFFF6, "3": 650, "4": 0x86A0, "5": 0x0001}
    return [
        {"name": "generic-int, one block of six words", "profile": gi, "fc": 3, "mem": mem_ok,
         "values": {"Voltage": "230.5", "Current": "12.34", "Power": "-10",
                    "Temperature": "25.0", "Energy": "1000.00"},
         "ok": 5, "gave_up": False, "reads": [[3, 0, 6]]},
        {"name": "generic-int, block fails, retried once, then gives up", "profile": gi,
         "fc": 3, "mem": {"0": 2305},
         "values": {"Voltage": None, "Current": None, "Power": None,
                    "Temperature": None, "Energy": None},
         "ok": 0, "gave_up": True, "reads": [[3, 0, 6], [3, 0, 6]]},
        {"name": "dkm440, one register unreadable", "profile": "dkm440.json", "fc": 3,
         "mem": dkm_mem(skip=("106",)), "values_subset": {
             "Supply_Voltage": "26.500", "MainBus_Voltage_L1": "230.000",
             "MainBus_Voltage_N": None, "MainBus_Current_N": "0.300"},
         "ok": 21, "gave_up": False, "read_count": 22},
        {"name": "dkm440, dead meter gives up after three reads", "profile": "dkm440.json",
         "fc": 3, "mem": {}, "ok": 0, "gave_up": True, "read_count": 3},
        {"name": "sdm630, input registers, merged requests", "profile": "examples/sdm630.json",
         "fc": 4, "mem": sdm_mem(),
         "values_subset": {"Voltage_L1": "230.00", "Current_L2": "5.50",
                           "Power_Total": "3800.00", "Freq": "50.00",
                           "Energy_Import": "1234.50"},
         "ok": 16, "gave_up": False, "reads": [[4, 0, 16], [4, 16, 2], [4, 30, 6], [4, 52, 2],
                                                [4, 70, 6]]},
    ]


def f32_words(x):
    import struct
    b = struct.pack(">f", x)
    return [(b[0] << 8) | b[1], (b[2] << 8) | b[3]]


def dkm_mem(skip=()):
    p = load("dkm440.json")
    known = {"Supply_Voltage": 26.5, "MainBus_Voltage_L1": 230.0, "MainBus_Voltage_N": 0.6,
             "MainBus_Current_N": 0.3}
    mem = {}
    for r in p["registers"]:
        v = known.get(r["key"], 1.0)
        hi, lo = f32_words(v)
        mem[str(r["address"])] = hi
        mem[str(r["address"] + 1)] = lo
    for s in skip:
        mem.pop(s)
    return mem


def sdm_mem():
    p = load("examples/sdm630.json")
    known = {"Voltage_L1": 230.0, "Current_L2": 5.5, "Power_Total": 3800.0, "Freq": 50.0,
             "Energy_Import": 1234.5}
    mem = {}
    for r in p["registers"]:
        hi, lo = f32_words(known.get(r["key"], 1.0))
        mem[str(r["address"])] = hi
        mem[str(r["address"] + 1)] = lo
    # words between registers (reserved in the real map) read as zero
    for a in range(0, 80):
        mem.setdefault(str(a), 0)
    return mem


def wire_cases():
    out = {}
    for name, f in (("dkm440", "dkm440.json"), ("sdm630", "examples/sdm630.json"),
                    ("generic-int", "examples/generic-int-scaled.json")):
        out[name] = {"file": f, "commands": [
            {"action": a, "args": args} for a, args in mp.wire_commands(load(f))]}
    return out


def record_cases():
    out = []
    for f, idx in (("dkm440.json", 0), ("dkm440.json", 21), ("examples/sdm630.json", 12),
                   ("examples/generic-int-scaled.json", 3),
                   ("examples/generic-int-scaled.json", 4)):
        p = load(f)
        _, regs = mp.resolve(p)
        out.append({"file": f, "index": idx, "hex": mp.binary_record(regs[idx]).hex()})
    return out


def build():
    return {
        "comment": "Generated by source/tools/gen_vectors.py. decode/plan/poll/validate "
                   "expectations are hand-written; wire/records are derived from "
                   "meterprofile.py. Run by tools/tests, meter-map/tests and firmware tests.",
        "decode": decode_cases(),
        "validate": validation_cases(),
        "plan": plan_cases(),
        "poll": poll_cases(),
        "wire": wire_cases(),
        "records": record_cases(),
    }


def render(data):
    # Compact enough to review in a diff: one case per line.
    lines = ["{"]
    keys = list(data)
    for ki, k in enumerate(keys):
        v = data[k]
        tail = "," if ki < len(keys) - 1 else ""
        if isinstance(v, list):
            lines.append(f'  "{k}": [')
            for i, item in enumerate(v):
                lines.append("    " + json.dumps(item, ensure_ascii=True)
                             + ("," if i < len(v) - 1 else ""))
            lines.append("  ]" + tail)
        elif isinstance(v, dict):
            lines.append(f'  "{k}": {{')
            items = list(v.items())
            for i, (name, item) in enumerate(items):
                lines.append(f'    "{name}": ' + json.dumps(item, ensure_ascii=True)
                             + ("," if i < len(items) - 1 else ""))
            lines.append("  }" + tail)
        else:
            lines.append(f'  "{k}": ' + json.dumps(v) + tail)
    lines.append("}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = render(build())
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur != text:
            sys.exit("vectors.json is stale: run python source/tools/gen_vectors.py")
        print("vectors.json is up to date")
    else:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote", os.path.relpath(OUT))
