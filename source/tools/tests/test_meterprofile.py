import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import meterprofile as mp

PROFILES = os.path.join(os.path.dirname(__file__), "..", "..", "meter-profiles")


def load(name):
    return mp.load_profile(os.path.join(PROFILES, name))


with open(os.path.join(PROFILES, "vectors.json"), encoding="utf-8") as f:
    VEC = json.load(f)


# ------------------------------------------------------------------ decode
@pytest.mark.parametrize("c", VEC["decode"], ids=lambda c: c["name"])
def test_decode(c):
    got = mp.decode_words(c["words"], c["type"], c["word_order"], c["byte_order"],
                          c["scale"], c["offset"])
    if c["expect"] is None:
        assert got is None
    else:
        assert got == pytest.approx(c["expect"], rel=1e-9, abs=1e-9)


# -------------------------------------------------------------- validation
@pytest.mark.parametrize("c", VEC["validate"], ids=lambda c: c["name"])
def test_validate(c):
    iss = mp.validate(c["profile"])
    assert sorted({i["code"] for i in iss if i["level"] == "error"}) == c["errors"]
    assert sorted({i["code"] for i in iss if i["level"] == "warn"}) == c["warns"]


@pytest.mark.parametrize("f", ["dkm440.json", "examples/sdm630.json",
                               "examples/generic-int-scaled.json"])
def test_shipped_profiles_are_clean(f):
    assert mp.validate(load(f)) == []


# -------------------------------------------------------------------- plan
@pytest.mark.parametrize("c", VEC["plan"], ids=lambda c: c["name"])
def test_plan(c):
    regs = [dict(r, address=r["address"]) for r in c["regs"]]
    got = [[fc, s, w, idx] for fc, s, w, idx in mp.plan_blocks(regs, c["max_block"])]
    assert got == c["blocks"]


# -------------------------------------------------------------------- poll
def make_reader(case):
    mem = {int(k): v for k, v in case["mem"].items()}
    log = []

    def read(fc, start, words):
        log.append([fc, start, words])
        if fc != case["fc"]:
            return None
        out = []
        for a in range(start, start + words):
            if a not in mem:
                return None
            out.append(mem[a])
        return out
    return read, log


@pytest.mark.parametrize("c", VEC["poll"], ids=lambda c: c["name"])
def test_poll(c):
    prof = load(c["profile"])
    gw = mp.GatewaySim(prof, analyzers=["an-01"])
    read, log = make_reader(c)
    values, ok, gave_up = gw.poll("an-01", read)
    assert ok == c["ok"]
    assert gave_up == c["gave_up"]
    if "values" in c:
        assert values == c["values"]
    for k, v in c.get("values_subset", {}).items():
        assert values[k] == v
    if "reads" in c:
        assert log == c["reads"]
    if "read_count" in c:
        assert len(log) == c["read_count"]


def test_poll_preserves_profile_order():
    prof = load("dkm440.json")
    gw = mp.GatewaySim(prof, analyzers=["an-01"])
    values, _, _ = gw.poll("an-01", lambda *a: None)
    assert list(values) == [r["key"] for r in prof["registers"]]


# -------------------------------------------------------------------- wire
def run_upload(gw, cmds):
    results = []
    for c in cmds:
        res = gw.handle(c["action"], c["args"])
        results.append(res)
        assert res is not None and res[0], (c["action"], res)
    return results


@pytest.mark.parametrize("name", ["dkm440", "sdm630", "generic-int"])
def test_wire_matches_vectors(name):
    got = [{"action": a, "args": args} for a, args in mp.wire_commands(load(VEC["wire"][name]["file"]))]
    assert got == VEC["wire"][name]["commands"]


@pytest.mark.parametrize("name", ["dkm440", "sdm630", "generic-int"])
def test_upload_roundtrip(name):
    prof = load(VEC["wire"][name]["file"])
    gw = mp.GatewaySim(load("dkm440.json"), analyzers=["an-01"])
    run_upload(gw, VEC["wire"][name]["commands"])
    stored = gw.get(prof["id"])
    assert stored is not None
    _, regs = mp.resolve(prof)
    assert [r["key"] for r in stored["regs"]] == [r["key"] for r in regs]
    for a, b in zip(stored["regs"], regs):
        for k in ("address", "fc", "type", "word_order", "byte_order", "scale", "offset", "decimals"):
            assert a[k] == b[k], (a["key"], k)
    # the profile comes back verbatim, for "pull from gateway and edit"
    assert stored["profile"] == mp.normalize(prof)


def test_every_wire_message_fits_the_gateway_buffer():
    for name in VEC["wire"]:
        for c in VEC["wire"][name]["commands"]:
            msg = json.dumps({"id": "c-xxxxxxxx", "action": c["action"], "args": c["args"]},
                             separators=(",", ":"), ensure_ascii=True)
            assert len(msg) < 1400, (name, c["action"], len(msg))


def test_binary_record_matches_vectors():
    for rec in VEC["records"]:
        _, regs = mp.resolve(load(rec["file"]))
        assert len(bytes.fromhex(rec["hex"])) == mp.RECORD_SIZE
        assert mp.binary_record(regs[rec["index"]]).hex() == rec["hex"]


def test_canonical_json_is_ascii_and_compact():
    s = mp.canonical_json({"a": "café €", "b": [1, 2.5, None, True]})
    assert s == '{"a":"caf\\u00e9 \\u20ac","b":[1,2.5,null,true]}'
    assert s.isascii()


def test_normalize_orders_keys_and_drops_unknown():
    p = mp.normalize({"registers": [{"address": 1, "key": "A", "zzz": 1}], "name": "n",
                      "id": "x", "junk": 1})
    assert list(p) == ["schema", "id", "name", "rev", "registers"]
    assert list(p["registers"][0]) == ["key", "address"]


# ------------------------------------------------------- gateway refusals
def fresh():
    return mp.GatewaySim(load("dkm440.json"), analyzers=["an-01", "an-02"])


def begin_args(**kw):
    a = {"id": "x1", "rev": 1, "n": 1, "blob_len": 2, "gap": 30, "tmo": 500, "blk": 1, "retries": 0}
    a.update(kw)
    return a


@pytest.mark.parametrize("kw", [
    {"id": "Bad"}, {"n": 0}, {"n": 49}, {"blob_len": 1}, {"blob_len": 9000},
    {"gap": 2001}, {"tmo": 10}, {"blk": 65}, {"retries": 4}, {"rev": -1},
])
def test_begin_refusals(kw):
    ok, _ = fresh().handle("profile_begin", begin_args(**kw))
    assert not ok


def test_regs_out_of_order_and_without_begin():
    gw = fresh()
    reg = {"k": "A", "a": 0, "f": 3, "t": "u16", "w": "big", "b": "big", "s": 1, "o": 0, "d": 0}
    assert gw.handle("profile_regs", {"id": "x1", "i": 0, "regs": [reg]})[0] is False
    gw.handle("profile_begin", begin_args(n=2))
    assert gw.handle("profile_regs", {"id": "x1", "i": 1, "regs": [reg]})[0] is False
    assert gw.handle("profile_regs", {"id": "x1", "i": 0, "regs": [reg]})[0] is True
    # a different id is not the upload in progress
    assert gw.handle("profile_regs", {"id": "zz", "i": 1, "regs": [reg]})[0] is False


@pytest.mark.parametrize("mut", [
    {"k": "bad key"}, {"t": "f16"}, {"a": 65535, "t": "f32"}, {"f": 1}, {"w": "mid"},
    {"s": 0}, {"d": 9}, {"a": -1},
])
def test_wire_register_validation(mut):
    gw = fresh()
    gw.handle("profile_begin", begin_args())
    reg = {"k": "A", "a": 0, "f": 3, "t": "u16", "w": "big", "b": "big", "s": 1, "o": 0, "d": 0}
    reg.update(mut)
    assert gw.handle("profile_regs", {"id": "x1", "i": 0, "regs": [reg]})[0] is False


def test_commit_checks_completeness_and_duplicates():
    gw = fresh()
    gw.handle("profile_begin", begin_args(n=2, blob_len=2))
    reg = {"k": "A", "a": 0, "f": 3, "t": "u16", "w": "big", "b": "big", "s": 1, "o": 0, "d": 0}
    gw.handle("profile_regs", {"id": "x1", "i": 0, "regs": [reg]})
    assert gw.handle("profile_commit", {"id": "x1"})[0] is False          # 1 of 2 regs
    gw.handle("profile_regs", {"id": "x1", "i": 1, "regs": [dict(reg)]})  # same key again
    gw.handle("profile_meta", {"id": "x1", "off": 0, "data": "{}"})
    ok, detail = gw.handle("profile_commit", {"id": "x1"})
    assert not ok and "duplicate" in detail
    assert gw.get("x1") is None                                           # nothing half-stored


def test_store_full_and_delete_rules():
    gw = fresh()
    prof = {"schema": 1, "id": "p0", "name": "n", "registers": [{"key": "A", "address": 0}]}
    for n in range(mp.MAX_PROFILES):
        prof["id"] = f"p{n}"
        run_upload(gw, [{"action": a, "args": r} for a, r in mp.wire_commands(prof)])
    ok, detail = gw.handle("profile_begin", begin_args(id="one-too-many"))
    assert not ok and "full" in detail
    # replacing an existing one is still allowed
    assert gw.handle("profile_begin", begin_args(id="p0"))[0] is True
    gw.handle("profile_assign", {"analyzer": "an-01", "profile": "p1"})
    ok, detail = gw.handle("profile_delete", {"id": "p1"})
    assert not ok and "an-01" in detail
    assert gw.handle("profile_delete", {"id": "p2"})[0] is True
    assert gw.handle("profile_delete", {"id": "nope"})[0] is False


def test_assign_rules_and_default():
    gw = fresh()
    assert gw.profile_for("an-01")["profile"]["id"] == "dkm440"
    assert gw.handle("profile_assign", {"analyzer": "an-09", "profile": "dkm440"})[0] is False
    assert gw.handle("profile_assign", {"analyzer": "an-01", "profile": "ghost"})[0] is False
    run_upload(gw, VEC["wire"]["sdm630"]["commands"])
    assert gw.handle("profile_assign", {"analyzer": "an-02", "profile": "sdm630"})[0] is True
    assert gw.profile_for("an-02")["profile"]["id"] == "sdm630"
    assert gw.profile_for("an-01")["profile"]["id"] == "dkm440"       # unaffected
    assert gw.listing()["assign"] == {"an-01": "dkm440", "an-02": "sdm630"}


def test_stored_profile_may_shadow_the_builtin():
    gw = fresh()
    prof = load("dkm440.json")
    prof["rev"] = 7
    run_upload(gw, [{"action": a, "args": r} for a, r in mp.wire_commands(prof)])
    assert gw.get("dkm440")["profile"]["rev"] == 7
    assert gw.handle("profile_delete", {"id": "dkm440"})[0] is True
    assert gw.get("dkm440")["profile"]["rev"] == 1                    # built-in is back


def test_unknown_action_is_not_a_profile_command():
    assert fresh().handle("ping", {}) is None


def test_malformed_args_are_refused_not_raised():
    gw = fresh()
    ok, _ = gw.handle("profile_regs", {"id": "x"})
    assert not ok
    ok, _ = gw.handle("profile_begin", {"id": "x1", "n": "many", "blob_len": 2})
    assert not ok


# ------------------------------------------------------- encode / simulator
@pytest.mark.parametrize("t,val", [("u16", 1234), ("i16", -321), ("u32", 123456), ("i32", -123456),
                                   ("f32", 26.5), ("u64", 10 ** 12), ("i64", -(10 ** 12)), ("f64", 1.25)])
@pytest.mark.parametrize("w", mp.ORDERS)
@pytest.mark.parametrize("b", mp.ORDERS)
def test_encode_decode_roundtrip(t, val, w, b):
    words = mp.encode_value(val, t, w, b)
    assert len(words) == mp.TYPES[t][0]
    assert mp.decode_words(words, t, w, b) == pytest.approx(val)


def test_encode_matches_known_layouts():
    assert mp.encode_value(26.5, "f32", "big", "big") == [0x41D4, 0x0000]
    assert mp.encode_value(26.5, "f32", "little", "big") == [0x0000, 0x41D4]
    assert mp.encode_value(26.5, "f32", "big", "little") == [0xD441, 0x0000]
    assert mp.encode_value(26.5, "f32", "little", "little") == [0x0000, 0xD441]
    assert mp.encode_value(230.5, "u16", scale=0.1) == [2305]


def test_encode_saturates_integers():
    assert mp.encode_value(1e9, "u16") == [0xFFFF]
    assert mp.encode_value(-5, "u16") == [0]
    assert mp.encode_value(-1e9, "i16") == [0x8000]


def test_describe_test_matches_firmware_text():
    reg = {"k": "T", "a": 260, "f": 3, "t": "f32", "w": "big", "b": "big", "s": 1, "o": 0, "d": 3}
    assert mp.describe_test(reg, [0x41D4, 0]) == "raw=41D4 0000 value=26.500"
    assert mp.describe_test(reg, [0x7FC0, 0]) == "raw=7FC0 0000 value=n/a (not finite)"
    assert mp.describe_test(None, [1, 0xABCD, 0xFFFF]) == "raw=0001 ABCD FFFF"
    u = dict(reg, t="u16", s=0.1, d=1)
    assert mp.describe_test(u, [2305]) == "raw=0901 value=230.5"


def test_profile_test_command():
    gw = fresh()
    mem = {260: 0x41D4, 261: 0}
    read = lambda fc, start, words: ([mem.get(start + i) for i in range(words)]
                                     if all(start + i in mem for i in range(words)) else None)
    ok, detail = gw.handle("profile_test", {"analyzer": "an-01", "address": 260, "type": "f32"}, read)
    assert ok and detail == "raw=41D4 0000 value=26.500"
    ok, detail = gw.handle("profile_test", {"analyzer": "an-01", "address": 260, "count": 2}, read)
    assert ok and detail == "raw=41D4 0000"
    assert gw.handle("profile_test", {"analyzer": "an-01", "address": 9}, read)[0] is False   # unreadable
    assert gw.handle("profile_test", {"analyzer": "zz", "address": 0}, read)[0] is False
    assert gw.handle("profile_test", {"analyzer": "an-01", "address": 70000}, read)[0] is False
    assert gw.handle("profile_test", {"analyzer": "an-01", "address": 0, "fc": 9}, read)[0] is False
    assert gw.handle("profile_test", {"analyzer": "an-01", "address": 0, "count": 9}, read)[0] is False
    assert gw.handle("profile_test", {"analyzer": "an-01", "address": 0, "type": "x"}, read)[0] is False


def test_poll_over_a_virtual_meter_round_trips_every_shipped_profile():
    """encode -> memory -> plan -> read -> decode -> format, for each profile."""
    for f in ("dkm440.json", "examples/sdm630.json", "examples/generic-int-scaled.json"):
        prof = load(f)
        timing, regs = mp.resolve(prof)
        want = {}
        mem = {}
        for i, r in enumerate(regs):
            val = round(10 + i * 1.5, 1)
            want[r["key"]] = val
            for k, w in enumerate(mp.encode_value(val, r["type"], r["word_order"], r["byte_order"],
                                                  r["scale"], r["offset"])):
                mem[(r["fc"], r["address"] + k)] = w

        def read(fc, start, words, mem=mem):
            got = [mem.get((fc, start + i)) for i in range(words)]
            return None if None in got else got
        gw = mp.GatewaySim(prof, analyzers=["an-01"])
        values, ok, gave_up = gw.poll("an-01", read)
        assert ok == len(regs) and not gave_up, f
        for r in regs:
            tol = 10 ** -r["decimals"] if r["decimals"] else 1
            assert float(values[r["key"]]) == pytest.approx(want[r["key"]], abs=tol), (f, r["key"])
