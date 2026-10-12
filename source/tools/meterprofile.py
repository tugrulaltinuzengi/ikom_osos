"""OSOS meter profiles - reference implementation (Python).

A meter profile (see source/meter-profiles/README.md) describes how a gateway
reads one kind of Modbus meter. This module is the executable specification:

* validate()      - schema check, returns issues with stable codes
* resolve()       - apply defaults, giving the exact numbers a gateway uses
* decode_words()  - 16-bit register words -> number (all types, all word orders)
* plan_blocks()   - merge adjacent registers into as few requests as allowed
* wire_commands() - the MQTT command sequence that uploads a profile
* GatewaySim      - an in-memory gateway profile store; the PC simulator
                    (fake_fleet.py) and the tests use it

The JavaScript UI (source/browser-hmi/meter-map/) and the C++ firmware
(source/firmware-esp8266/osos_gw8266/profile*.h) implement the same rules and run
the same cases from source/meter-profiles/vectors.json.
"""
import json
import math
import re
import struct

SCHEMA = 1

# Limits. The firmware announces its own in the retained `profiles` topic; these
# are the ESP8266 build's, which are the tightest.
MAX_REGS = 48
MAX_VIEWS = 8
MAX_VIEW_KEYS = 24
MAX_PROFILES = 6          # stored on the gateway, not counting the built-in one
MAX_BLOB = 8192           # bytes of display metadata (the profile JSON itself)
MAX_REQUEST_MS = 8000     # timeout_ms x (retries + 1): one request must not outlast the keepalive
REGS_PER_CHUNK = 6
META_CHUNK = 400

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,31}$")
VIEW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,23}$")   # "L1" etc: drawn commands name views

# type -> (16-bit words, wire code). The wire code is also the binary record code.
TYPES = {
    "u16": (1, 0), "i16": (1, 1),
    "u32": (2, 2), "i32": (2, 3), "f32": (2, 4),
    "u64": (4, 5), "i64": (4, 6), "f64": (4, 7),
}
ORDERS = ("big", "little")

TIMING_DEFAULTS = {"read_gap_ms": 30, "timeout_ms": 500, "max_block": 1, "retries": 0}
TIMING_RANGES = {
    "read_gap_ms": (0, 2000), "timeout_ms": (50, 5000),
    "max_block": (1, 64), "retries": (0, 3),
}
REG_DEFAULTS = {
    "fc": 3, "type": "f32", "word_order": "big", "byte_order": "big",
    "scale": 1, "offset": 0,
}

TOP_KEYS = ("schema", "id", "name", "vendor", "model", "notes", "rev",
            "transport", "timing", "defaults", "registers", "views")
REG_KEYS = ("key", "address", "fc", "type", "word_order", "byte_order",
            "scale", "offset", "decimals", "unit", "label", "group")
DEFAULT_KEYS = ("fc", "type", "word_order", "byte_order", "scale", "offset")
VIEW_KEYS = ("id", "label", "keys")


# --------------------------------------------------------------------------- json
def canonical_json(obj):
    """Compact, insertion-ordered, ASCII-only. JavaScript produces the same bytes."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True)


def _tidy_number(v):
    """1.0 -> 1, so Python and JavaScript serialise the same profile to the same bytes."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


def normalize(profile):
    """Known keys only, in canonical order; `schema` and `rev` always present."""
    out = {}
    src = dict(profile)
    src.setdefault("schema", SCHEMA)
    src.setdefault("rev", 1)
    for k in TOP_KEYS:
        if k not in src:
            continue
        v = src[k]
        if k == "defaults" and isinstance(v, dict):
            v = {dk: _tidy_number(v[dk]) for dk in DEFAULT_KEYS if dk in v}
        elif k == "timing" and isinstance(v, dict):
            v = {tk: v[tk] for tk in TIMING_DEFAULTS if tk in v}
        elif k == "registers" and isinstance(v, list):
            v = [{rk: _tidy_number(r[rk]) for rk in REG_KEYS if rk in r}
                 if isinstance(r, dict) else r for r in v]
        elif k == "views" and isinstance(v, list):
            v = [{vk: w[vk] for vk in VIEW_KEYS if vk in w} if isinstance(w, dict) else w
                 for w in v]
        out[k] = v
    return out


def dump_profile(profile):
    """Human-friendly file layout: one register per line."""
    p = normalize(profile)
    lines = ["{"]
    keys = [k for k in TOP_KEYS if k in p]
    for n, k in enumerate(keys):
        comma = "," if n < len(keys) - 1 else ""
        if k == "registers":
            lines.append('  "registers": [')
            for i, r in enumerate(p[k]):
                lines.append("    " + json.dumps(r, ensure_ascii=False)
                             + ("," if i < len(p[k]) - 1 else ""))
            lines.append("  ]" + comma)
        elif k == "views":
            lines.append('  "views": [')
            for i, w in enumerate(p[k]):
                lines.append("    " + json.dumps(w, ensure_ascii=False)
                             + ("," if i < len(p[k]) - 1 else ""))
            lines.append("  ]" + comma)
        else:
            lines.append(f'  "{k}": ' + json.dumps(p[k], ensure_ascii=False) + comma)
    lines.append("}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------- validate
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _issue(level, code, path, msg):
    return {"level": level, "code": code, "path": path, "msg": msg}


def validate(profile, max_regs=MAX_REGS):
    """-> list of issues {level: error|warn, code, path, msg}. No `error` == usable."""
    iss = []
    err = lambda code, path, msg: iss.append(_issue("error", code, path, msg))
    warn = lambda code, path, msg: iss.append(_issue("warn", code, path, msg))

    if not isinstance(profile, dict):
        err("profile.type", "", "profile must be an object")
        return iss

    if profile.get("schema") != SCHEMA:
        err("schema.unsupported", "schema", f"schema must be {SCHEMA}")
    pid = profile.get("id")
    if not isinstance(pid, str) or not ID_RE.match(pid):
        err("id.invalid", "id", "id must match [a-z0-9][a-z0-9_-]{0,23}")
    name = profile.get("name")
    if not isinstance(name, str) or not name.strip():
        err("name.missing", "name", "name is required")
    elif len(name) > 48:
        err("name.long", "name", "name is longer than 48 characters")
    for k, lim in (("vendor", 48), ("model", 48), ("notes", 200)):
        if k in profile and (not isinstance(profile[k], str) or len(profile[k]) > lim):
            err("text.invalid", k, f"{k} must be a string of at most {lim} characters")
    if "rev" in profile and not (_int(profile["rev"]) and 0 <= profile["rev"] <= 65535):
        err("rev.invalid", "rev", "rev must be an integer 0..65535")
    if "transport" in profile and profile["transport"] not in ("tcp", "rtu"):
        err("transport.invalid", "transport", "transport must be tcp or rtu")

    timing = profile.get("timing", {})
    if not isinstance(timing, dict):
        err("timing.invalid", "timing", "timing must be an object")
    else:
        for k, (lo, hi) in TIMING_RANGES.items():
            if k in timing and not (_int(timing[k]) and lo <= timing[k] <= hi):
                err("timing.range", f"timing.{k}", f"{k} must be an integer {lo}..{hi}")
        t = {**TIMING_DEFAULTS, **timing}
        if (all(_int(t[k]) for k in ("timeout_ms", "retries")) and
                t["timeout_ms"] * (t["retries"] + 1) > MAX_REQUEST_MS):
            err("timing.budget", "timing",
                f"timeout_ms x (retries + 1) must not exceed {MAX_REQUEST_MS} ms")

    defaults = profile.get("defaults", {})
    if not isinstance(defaults, dict):
        err("defaults.invalid", "defaults", "defaults must be an object")
        defaults = {}
    else:
        _check_reg_fields(defaults, "defaults", err)

    regs = profile.get("registers")
    if not isinstance(regs, list) or not regs:
        err("registers.missing", "registers", "at least one register is required")
        regs = []
    elif len(regs) > max_regs:
        err("registers.toomany", "registers", f"at most {max_regs} registers")

    seen = {}
    spans = []
    for i, r in enumerate(regs):
        path = f"registers[{i}]"
        if not isinstance(r, dict):
            err("reg.type", path, "register must be an object")
            continue
        key = r.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            err("reg.key.invalid", path + ".key", "key must match [A-Za-z0-9_]{1,31}")
        elif key in seen:
            err("reg.key.duplicate", path + ".key", f"duplicate key {key}")
        else:
            seen[key] = i
        _check_reg_fields(r, path, err)
        res = _resolve_reg(r, defaults)
        addr = r.get("address")
        if not _int(addr) or not 0 <= addr <= 65535:
            err("reg.address.range", path + ".address", "address must be an integer 0..65535")
        elif res["type"] in TYPES:
            if addr + TYPES[res["type"]][0] > 65536:
                err("reg.address.range", path + ".address",
                    "register runs past address 65535")
            else:
                spans.append((res["fc"], addr, addr + TYPES[res["type"]][0], key, i))
        for k, lim in (("unit", 8), ("label", 40), ("group", 24)):
            if k in r and (not isinstance(r[k], str) or len(r[k]) > lim):
                err("text.invalid", path + "." + k,
                    f"{k} must be a string of at most {lim} characters")
        if "decimals" in r and not (_int(r["decimals"]) and 0 <= r["decimals"] <= 6):
            err("reg.decimals", path + ".decimals", "decimals must be an integer 0..6")

    # Partial overlap between registers is almost always a wrong address or type.
    # Identical spans are fine (the same value shown twice, or via two scales).
    spans.sort()
    for a in range(len(spans)):
        for b in range(a + 1, len(spans)):
            fa, sa, ea, ka, ia = spans[a]
            fb, sb, eb, kb, ib = spans[b]
            if fb != fa or sb >= ea:
                break
            if (sa, ea) != (sb, eb):
                warn("reg.overlap", f"registers[{ib}]",
                     f"{kb} partly overlaps {ka}; check address or type")

    views = profile.get("views", [])
    if not isinstance(views, list):
        err("views.invalid", "views", "views must be an array")
    else:
        if len(views) > MAX_VIEWS:
            err("views.toomany", "views", f"at most {MAX_VIEWS} views")
        vids = set()
        for i, w in enumerate(views):
            path = f"views[{i}]"
            if not isinstance(w, dict):
                err("view.type", path, "view must be an object")
                continue
            vid = w.get("id")
            if not isinstance(vid, str) or not VIEW_ID_RE.match(vid):
                err("view.id.invalid", path + ".id", "view id must match [A-Za-z0-9][A-Za-z0-9_-]{0,23}")
            elif vid in vids:
                err("view.id.duplicate", path + ".id", f"duplicate view id {vid}")
            else:
                vids.add(vid)
            if "label" in w and (not isinstance(w["label"], str) or len(w["label"]) > 24):
                err("text.invalid", path + ".label", "label must be a string of at most 24 characters")
            keys = w.get("keys")
            if not isinstance(keys, list) or not keys:
                err("view.keys.missing", path + ".keys", "a view needs at least one key")
                continue
            if len(keys) > MAX_VIEW_KEYS:
                err("view.keys.toomany", path + ".keys", f"at most {MAX_VIEW_KEYS} keys")
            for k in keys:
                if k not in seen:
                    err("view.keys.unknown", path + ".keys", f"unknown register key {k}")

    # The telemetry frame must fit the gateway's publish budget.
    if regs and all(isinstance(r, dict) and isinstance(r.get("key"), str) for r in regs):
        if telemetry_budget(regs) > 2000:
            warn("telemetry.large", "registers", "telemetry frame may exceed 2000 bytes")

    if len(canonical_json(profile)) > MAX_BLOB:
        err("blob.toolarge", "", f"profile JSON exceeds {MAX_BLOB} bytes")
    return iss


def _check_reg_fields(r, path, err):
    if "fc" in r and r["fc"] not in (3, 4):
        err("reg.fc.invalid", path + ".fc", "fc must be 3 or 4")
    if "type" in r and r["type"] not in TYPES:
        err("reg.type.invalid", path + ".type", "type must be one of " + " ".join(TYPES))
    for k in ("word_order", "byte_order"):
        if k in r and r[k] not in ORDERS:
            err("reg.order.invalid", path + "." + k, f"{k} must be big or little")
    for k in ("scale", "offset"):
        if k in r and not _num(r[k]):
            err("reg.number.invalid", path + "." + k, f"{k} must be a finite number")
    if "scale" in r and _num(r["scale"]) and r["scale"] == 0:
        err("reg.scale.zero", path + ".scale", "scale of 0 would zero every reading")


def telemetry_budget(regs):
    """Worst-case bytes of the telemetry `values` object for these registers."""
    return 140 + sum(len(r["key"]) + 16 for r in regs)


# ------------------------------------------------------------------------ resolve
def _resolve_reg(r, defaults):
    out = {}
    for k, dv in REG_DEFAULTS.items():
        out[k] = r.get(k, defaults.get(k, dv))
    return out


def resolve(profile):
    """Apply defaults. -> (timing, [register]) where every register carries
    key, address, fc, type, word_order, byte_order, scale, offset, decimals -
    precisely the numbers the gateway needs, nothing implicit."""
    timing = dict(TIMING_DEFAULTS)
    timing.update(profile.get("timing", {}))
    defaults = profile.get("defaults", {})
    regs = []
    for r in profile["registers"]:
        d = _resolve_reg(r, defaults)
        d["key"] = r["key"]
        d["address"] = r["address"]
        if "decimals" in r:
            d["decimals"] = r["decimals"]
        else:
            floaty = d["type"] in ("f32", "f64")
            d["decimals"] = 3 if (floaty or d["scale"] != 1) else 0
        regs.append(d)
    return timing, regs


# ------------------------------------------------------------------------- decode
def _swap_bytes(w):
    return ((w & 0xFF) << 8) | (w >> 8)


def raw_bits(words, rtype, word_order="big", byte_order="big"):
    """Words as read from the wire -> the unsigned integer of the whole value."""
    n = TYPES[rtype][0]
    if len(words) != n:
        raise ValueError(f"{rtype} needs {n} words")
    ws = [_swap_bytes(w) for w in words] if byte_order == "little" else list(words)
    if word_order == "little":
        ws.reverse()
    v = 0
    for w in ws:
        v = (v << 16) | w
    return v


def decode_words(words, rtype, word_order="big", byte_order="big", scale=1, offset=0):
    """-> float/int, or None for a non-finite float (a failed read)."""
    bits = raw_bits(words, rtype, word_order, byte_order)
    if rtype in ("u16", "u32", "u64"):
        raw = bits
    elif rtype == "i16":
        raw = bits - 0x10000 if bits & 0x8000 else bits
    elif rtype == "i32":
        raw = bits - (1 << 32) if bits & 0x80000000 else bits
    elif rtype == "i64":
        raw = bits - (1 << 64) if bits & (1 << 63) else bits
    elif rtype == "f32":
        raw = struct.unpack(">f", bits.to_bytes(4, "big"))[0]
    else:
        raw = struct.unpack(">d", bits.to_bytes(8, "big"))[0]
    if isinstance(raw, float) and not math.isfinite(raw):
        return None
    return raw * scale + offset


def encode_value(value, rtype, word_order="big", byte_order="big", scale=1, offset=0):
    """Inverse of decode_words: a number -> the register words a meter would hold.
    The simulator uses it to build a virtual meter memory from a profile."""
    raw = (value - offset) / scale
    if rtype == "f32":
        bits = int.from_bytes(struct.pack(">f", raw), "big")
    elif rtype == "f64":
        bits = int.from_bytes(struct.pack(">d", raw), "big")
    else:
        n = TYPES[rtype][0] * 16
        r = int(round(raw))
        if rtype.startswith("i"):
            r = max(-(1 << (n - 1)), min((1 << (n - 1)) - 1, r))
        else:
            r = max(0, min((1 << n) - 1, r))
        bits = r & ((1 << n) - 1)
    n = TYPES[rtype][0]
    ws = [(bits >> (16 * (n - 1 - i))) & 0xFFFF for i in range(n)]
    if word_order == "little":
        ws.reverse()
    if byte_order == "little":
        ws = [_swap_bytes(w) for w in ws]
    return ws


def format_value(v, decimals):
    return f"{v:.{decimals}f}"


# --------------------------------------------------------------------------- plan
def plan_blocks(regs, max_block):
    """Group register indexes into requests. -> [(fc, start, words, [index...])].

    Registers are merged when they share a function code and touch or overlap,
    as long as the block stays within `max_block` words. A block is never smaller
    than its widest register, so max_block=1 means one request per register.
    """
    order = sorted(range(len(regs)), key=lambda i: (regs[i]["fc"], regs[i]["address"], i))
    blocks = []
    for i in order:
        r = regs[i]
        end = r["address"] + TYPES[r["type"]][0]
        if blocks:
            fc, start, bend, idxs = blocks[-1]
            if fc == r["fc"] and r["address"] <= bend and max(bend, end) - start <= max_block:
                blocks[-1] = (fc, start, max(bend, end), idxs + [i])
                continue
        blocks.append((r["fc"], r["address"], end, [i]))
    return [(fc, start, end - start, idxs) for fc, start, end, idxs in blocks]


def extract_words(block, reg, block_words):
    start = block[1]
    n = TYPES[reg["type"]][0]
    o = reg["address"] - start
    return block_words[o:o + n]


# --------------------------------------------------------------------------- wire
def binary_record(reg):
    """The 56-byte record the firmware stores per register (little-endian):
    key[32] scale:f64 offset:f64 address:u16 fc:u8 type:u8 order:u8 decimals:u8 pad[2]
    order bit0 = word order little, bit1 = byte order little."""
    order = (1 if reg["word_order"] == "little" else 0) | \
            (2 if reg["byte_order"] == "little" else 0)
    return struct.pack(
        "<32sddHBBBB2x", reg["key"].encode("ascii"), reg["scale"], reg["offset"],
        reg["address"], reg["fc"], TYPES[reg["type"]][1], order, reg["decimals"])


RECORD_SIZE = 56


def wire_name(name):
    """Profile name as sent to the gateway: at most 44 UTF-8 bytes, cut on a
    character boundary (the gateway keeps it in a fixed 48-byte field)."""
    return name.encode("utf-8")[:44].decode("utf-8", "ignore")


def wire_commands(profile):
    """-> [(action, args)] to upload `profile` to a gateway, in order.
    Registers travel fully resolved (short keys); the gateway never sees
    `defaults`. The profile JSON itself rides along verbatim as opaque metadata
    so any client can later read the profile back from the gateway."""
    p = normalize(profile)
    timing, regs = resolve(p)
    blob = canonical_json(p)
    cmds = [("profile_begin", {
        "id": p["id"], "name": wire_name(p["name"]), "rev": p["rev"], "n": len(regs),
        "blob_len": len(blob),
        "gap": timing["read_gap_ms"], "tmo": timing["timeout_ms"],
        "blk": timing["max_block"], "retries": timing["retries"],
    })]
    for i in range(0, len(regs), REGS_PER_CHUNK):
        chunk = []
        for r in regs[i:i + REGS_PER_CHUNK]:
            chunk.append({"k": r["key"], "a": r["address"], "f": r["fc"],
                          "t": r["type"], "w": r["word_order"], "b": r["byte_order"],
                          "s": r["scale"], "o": r["offset"], "d": r["decimals"]})
        cmds.append(("profile_regs", {"id": p["id"], "i": i, "regs": chunk}))
    for off in range(0, len(blob), META_CHUNK):
        cmds.append(("profile_meta", {"id": p["id"], "off": off,
                                      "data": blob[off:off + META_CHUNK]}))
    cmds.append(("profile_commit", {"id": p["id"]}))
    return cmds


# ------------------------------------------------------------------------ gateway
class GatewaySim:
    """In-memory model of a gateway's profile storage and profile commands.

    Mirrors profile_cmd.h: same checks, same order, same refusal reasons, so the
    PC simulator behaves like the firmware. `builtin` is the profile that is
    always available (the DKM-440)."""

    def __init__(self, builtin, analyzers=()):
        self.builtin = normalize(builtin)
        self.stored = {}                  # id -> {"profile": dict, "timing": .., "regs": [..]}
        self.assign = {}                  # analyzer id -> profile id
        self.default_profile = self.builtin["id"]
        self.analyzers = list(analyzers)
        self.up = None                    # upload in progress
        self.dirty = True                 # profiles topic needs republishing
        self.changed_profile = None       # set by commit/delete: analyzers using it republish
        self.changed_analyzer = None      # set by assign

    # -- lookup
    def profile_for(self, aid):
        pid = self.assign.get(aid, self.default_profile)
        return self.get(pid) or self.get(self.default_profile)

    def get(self, pid):
        if pid in self.stored:
            return self.stored[pid]
        if pid == self.builtin["id"]:
            t, r = resolve(self.builtin)
            return {"profile": self.builtin, "timing": t, "regs": r,
                    "rev": self.builtin["rev"], "name": self.builtin["name"]}
        return None

    def listing(self):
        items = [{"id": pid, "rev": s["rev"], "n": len(s["regs"]), "name": s["name"]}
                 for pid, s in self.stored.items()]
        if self.builtin["id"] not in self.stored:
            items.insert(0, {"id": self.builtin["id"], "rev": self.builtin["rev"],
                             "n": len(self.builtin["registers"]),
                             "name": self.builtin["name"], "builtin": True})
        return {"v": 2, "profiles": items,
                "assign": {a: self.assign.get(a, self.default_profile) for a in self.analyzers},
                "cap": {"regs": MAX_REGS, "profiles": MAX_PROFILES, "blob": MAX_BLOB}}

    # -- commands
    def handle(self, action, args, read=None):
        """-> (ok, detail) or None if `action` is not a profile command.
        `read(fc, start, words)` serves profile_test; without it that command fails."""
        self.changed_profile = self.changed_analyzer = None
        if action == "profile_test":
            try:
                return self._test(args or {}, read)
            except (KeyError, TypeError, ValueError) as e:
                return False, f"bad args: {e}"
        fn = {
            "profile_begin": self._begin, "profile_regs": self._regs,
            "profile_meta": self._meta, "profile_commit": self._commit,
            "profile_delete": self._delete, "profile_assign": self._assign,
            "profile_list": self._list,
        }.get(action)
        if fn is None:
            return None
        try:
            return fn(args or {})
        except (KeyError, TypeError, ValueError) as e:       # malformed args
            return False, f"bad args: {e}"

    def _begin(self, a):
        self.up = None                    # a new begin always cancels the old upload
        pid = a.get("id", "")
        if not isinstance(pid, str) or not ID_RE.match(pid):
            return False, "bad profile id"
        n, bl = a.get("n", 0), a.get("blob_len", 0)
        if not (_int(n) and 1 <= n <= MAX_REGS):
            return False, f"n out of range 1..{MAX_REGS}"
        if not (_int(bl) and 2 <= bl <= MAX_BLOB):
            return False, f"blob_len out of range 2..{MAX_BLOB}"
        t = {"read_gap_ms": a.get("gap", 30), "timeout_ms": a.get("tmo", 500),
             "max_block": a.get("blk", 1), "retries": a.get("retries", 0)}
        for k, (lo, hi) in TIMING_RANGES.items():
            if not (_int(t[k]) and lo <= t[k] <= hi):
                return False, f"{k} out of range {lo}..{hi}"
        if t["timeout_ms"] * (t["retries"] + 1) > MAX_REQUEST_MS:
            return False, f"timeout x attempts exceeds {MAX_REQUEST_MS} ms"
        rev = a.get("rev", 1)
        if not (_int(rev) and 0 <= rev <= 65535):
            return False, "rev out of range 0..65535"
        if pid not in self.stored and len(self.stored) >= MAX_PROFILES:
            return False, f"profile store full ({MAX_PROFILES}); delete one first"
        name = a.get("name", "")
        if not isinstance(name, str) or len(name.encode("utf-8")) > 44:
            return False, "name too long"
        self.up = {"id": pid, "name": name, "rev": rev, "n": n, "blob_len": bl, "timing": t,
                   "regs": [], "blob": ""}
        return True, f"upload {pid} started"

    def _need_upload(self, a):
        u = self.up
        if u is None or u["id"] != a.get("id"):
            return None
        return u

    def _regs(self, a):
        u = self._need_upload(a)
        if u is None:
            return False, "no upload in progress for that id"
        if a.get("i") != len(u["regs"]):
            return False, f"out of order, expected index {len(u['regs'])}"
        chunk = a.get("regs")
        if not isinstance(chunk, list) or not chunk or len(chunk) > 8:
            return False, "regs must hold 1..8 entries"
        if len(u["regs"]) + len(chunk) > u["n"]:
            return False, "more registers than declared"
        for r in chunk:
            bad = _check_wire_reg(r)
            if bad:
                return False, f"reg {len(u['regs'])}: {bad}"
            u["regs"].append(r)
        return True, f"{len(u['regs'])}/{u['n']} regs"

    def _meta(self, a):
        u = self._need_upload(a)
        if u is None:
            return False, "no upload in progress for that id"
        if a.get("off") != len(u["blob"]):
            return False, f"out of order, expected offset {len(u['blob'])}"
        data = a.get("data")
        if not isinstance(data, str) or not data:
            return False, "data must be a non-empty string"
        if len(u["blob"]) + len(data) > u["blob_len"]:
            return False, "more metadata than declared"
        u["blob"] += data
        return True, f"{len(u['blob'])}/{u['blob_len']} bytes"

    def _commit(self, a):
        u = self._need_upload(a)
        if u is None:
            return False, "no upload in progress for that id"
        if len(u["regs"]) != u["n"]:
            return False, f"incomplete: {len(u['regs'])}/{u['n']} regs"
        if len(u["blob"]) != u["blob_len"]:
            return False, f"incomplete: {len(u['blob'])}/{u['blob_len']} bytes"
        keys = [r["k"] for r in u["regs"]]
        if len(set(keys)) != len(keys):
            return False, "duplicate register key"
        if not (u["blob"].startswith("{") and u["blob"].endswith("}")):
            return False, "metadata is not a JSON object"
        try:
            prof = json.loads(u["blob"])
        except ValueError:
            return False, "metadata is not valid JSON"
        regs = []
        for r in u["regs"]:
            regs.append({"key": r["k"], "address": r["a"], "fc": r["f"], "type": r["t"],
                         "word_order": r["w"], "byte_order": r["b"],
                         "scale": r["s"], "offset": r["o"], "decimals": r["d"]})
        self.stored[u["id"]] = {"profile": prof, "timing": u["timing"], "regs": regs,
                                "rev": u["rev"], "name": u["name"]}
        self.up = None
        self.dirty = True
        self.changed_profile = u["id"]
        return True, f"stored {u['id']} rev {u['rev']} ({len(regs)} regs)"

    def _delete(self, a):
        pid = a.get("id")
        if pid not in self.stored:
            return False, "no such stored profile"
        users = [x for x, p in self.assign.items() if p == pid]
        if users:
            return False, f"in use by {', '.join(users)}"
        del self.stored[pid]
        self.dirty = True
        self.changed_profile = pid
        return True, f"deleted {pid}"

    def _assign(self, a):
        aid, pid = a.get("analyzer"), a.get("profile")
        if aid not in self.analyzers:
            return False, f"no such analyzer: {aid}"
        if self.get(pid) is None:
            return False, f"no such profile: {pid}"
        self.assign[aid] = pid
        self.dirty = True
        self.changed_analyzer = aid
        return True, f"{aid} reads as {pid}"

    def _test(self, a, read):
        aid = a.get("analyzer")
        if aid not in self.analyzers:
            return False, f"no such analyzer: {aid}"
        addr, fc = a.get("address"), a.get("fc", 3)
        if not _int(addr) or not 0 <= addr <= 65535:
            return False, "address out of range"
        if fc not in (3, 4):
            return False, "fc must be 3 or 4"
        count = a.get("count", 0)
        if count:
            if not (_int(count) and 1 <= count <= 8 and addr + count <= 65536):
                return False, "count must be 1..8 within the address space"
            reg, words = None, count
        else:
            reg = {"k": "T", "a": addr, "f": fc, "t": a.get("type", "f32"),
                   "w": a.get("word_order", "big"), "b": a.get("byte_order", "big"),
                   "s": a.get("scale", 1), "o": a.get("offset", 0), "d": a.get("decimals", 3)}
            bad = _check_wire_reg(reg)
            if bad:
                return False, bad
            words = TYPES[reg["t"]][0]
        if read is None:
            return False, "read failed (no meter)"
        got = read(fc, addr, words)
        if got is None:
            return False, "read failed (modbus exception 0x00)"
        return True, describe_test(reg, got)

    def affected_analyzers(self):
        """Analyzers whose retained `profile` topic must be republished after the
        last command (a profile they use changed, or they were reassigned)."""
        out = []
        for aid in self.analyzers:
            uses = self.changed_profile and self.profile_for(aid)["profile"]["id"] == self.changed_profile
            if uses or aid == self.changed_analyzer:
                out.append(aid)
        return out

    def blob_for(self, aid):
        """The retained `a/<id>/profile` payload: the profile JSON, verbatim."""
        return canonical_json(self.profile_for(aid)["profile"])

    def _list(self, a):
        self.dirty = True
        return True, f"{len(self.stored)} stored"

    # -- polling
    def poll(self, aid, read):
        """Read every register of `aid`'s profile. `read(fc, start, words)` returns
        the list of words or None on failure. -> (values, ok_count, gave_up) where
        values maps key -> formatted string or None, in profile order."""
        s = self.profile_for(aid)
        regs, t = s["regs"], s["timing"]
        values = {r["key"]: None for r in regs}
        ok = fails = 0
        gave_up = False
        for fc, start, words, idxs in plan_blocks(regs, t["max_block"]):
            got = None
            for _ in range(1 + t["retries"]):
                got = read(fc, start, words)
                if got is not None:
                    break
            for i in idxs:
                r = regs[i]
                v = None
                if got is not None:
                    v = decode_words(extract_words((fc, start), r, got), r["type"],
                                     r["word_order"], r["byte_order"], r["scale"], r["offset"])
                if v is None:
                    fails += 1
                else:
                    values[r["key"]] = format_value(v, r["decimals"])
                    ok += 1
                    fails = 0
            if fails >= 3:
                gave_up = True
                break
        return values, ok, gave_up


def describe_test(reg, words):
    """Ack text for profile_test, identical to ProfileStore::describeTest."""
    out = "raw=" + " ".join(f"{w:04X}" for w in words)
    if reg is None:
        return out
    v = decode_words(words, reg["t"], reg["w"], reg["b"], reg["s"], reg["o"])
    if v is None:
        return out + " value=n/a (not finite)"
    return out + " value=" + format_value(v, reg["d"])


def _check_wire_reg(r):
    if not isinstance(r, dict):
        return "not an object"
    if not isinstance(r.get("k"), str) or not KEY_RE.match(r["k"]):
        return "bad key"
    t = r.get("t")
    if t not in TYPES:
        return "bad type"
    a = r.get("a")
    if not _int(a) or not 0 <= a or a + TYPES[t][0] > 65536:
        return "address out of range"
    if r.get("f") not in (3, 4):
        return "fc must be 3 or 4"
    if r.get("w") not in ORDERS or r.get("b") not in ORDERS:
        return "bad word/byte order"
    if not _num(r.get("s")) or r["s"] == 0 or not _num(r.get("o")):
        return "bad scale/offset"
    if not (_int(r.get("d")) and 0 <= r["d"] <= 6):
        return "decimals out of range"
    return None


def load_profile(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
