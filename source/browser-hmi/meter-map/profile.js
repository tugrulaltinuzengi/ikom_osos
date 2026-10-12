// OSOS meter profiles - JavaScript port of source/tools/meterprofile.py.
//
// The same rules as the Python reference and the firmware, checked against the
// same source/meter-profiles/vectors.json (see tests/profile.test.js). Used by the
// browser HMI and, unchanged, by the Android app's WebView.
//
// Works in a page (global OsosProfile) and in Node (require).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.OsosProfile = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const SCHEMA = 1;
  const MAX_REGS = 48, MAX_VIEWS = 8, MAX_VIEW_KEYS = 24, MAX_PROFILES = 6;
  const MAX_BLOB = 8192, MAX_REQUEST_MS = 8000;
  const REGS_PER_CHUNK = 6, META_CHUNK = 400;

  const ID_RE = /^[a-z0-9][a-z0-9_-]{0,23}$/;
  const KEY_RE = /^[A-Za-z0-9_]{1,31}$/;
  const VIEW_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,23}$/;

  // type -> [16-bit words, wire code]
  const TYPES = {
    u16: [1, 0], i16: [1, 1], u32: [2, 2], i32: [2, 3], f32: [2, 4],
    u64: [4, 5], i64: [4, 6], f64: [4, 7],
  };
  const ORDERS = ["big", "little"];
  const TIMING_DEFAULTS = { read_gap_ms: 30, timeout_ms: 500, max_block: 1, retries: 0 };
  const TIMING_RANGES = {
    read_gap_ms: [0, 2000], timeout_ms: [50, 5000], max_block: [1, 64], retries: [0, 3],
  };
  const REG_DEFAULTS = {
    fc: 3, type: "f32", word_order: "big", byte_order: "big", scale: 1, offset: 0,
  };
  const TOP_KEYS = ["schema", "id", "name", "vendor", "model", "notes", "rev",
    "transport", "timing", "defaults", "registers", "views"];
  const REG_KEYS = ["key", "address", "fc", "type", "word_order", "byte_order",
    "scale", "offset", "decimals", "unit", "label", "group"];
  const DEFAULT_KEYS = ["fc", "type", "word_order", "byte_order", "scale", "offset"];
  const VIEW_KEYS = ["id", "label", "keys"];

  const isObj = v => v !== null && typeof v === "object" && !Array.isArray(v);
  const isInt = v => typeof v === "number" && Number.isInteger(v);
  const isNum = v => typeof v === "number" && Number.isFinite(v);
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const pick = (o, keys) => {
    const out = {};
    for (const k of keys) if (has(o, k)) out[k] = o[k];
    return out;
  };

  // ------------------------------------------------------------------- json
  // Compact, insertion-ordered, ASCII-only: the bytes Python produces.
  function canonicalJson(obj) {
    return JSON.stringify(obj).replace(/[\u007f-￿]/g,
      c => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  }

  function normalize(profile) {
    const src = Object.assign({}, profile);
    if (!has(src, "schema")) src.schema = SCHEMA;
    if (!has(src, "rev")) src.rev = 1;
    const out = {};
    for (const k of TOP_KEYS) {
      if (!has(src, k)) continue;
      let v = src[k];
      if (k === "defaults" && isObj(v)) v = pick(v, DEFAULT_KEYS);
      else if (k === "timing" && isObj(v)) v = pick(v, Object.keys(TIMING_DEFAULTS));
      else if (k === "registers" && Array.isArray(v)) v = v.map(r => isObj(r) ? pick(r, REG_KEYS) : r);
      else if (k === "views" && Array.isArray(v)) v = v.map(w => isObj(w) ? pick(w, VIEW_KEYS) : w);
      out[k] = v;
    }
    return out;
  }

  // -------------------------------------------------------------- validation
  function issue(level, code, path, msg) { return { level, code, path, msg }; }

  function checkRegFields(r, path, err) {
    if (has(r, "fc") && r.fc !== 3 && r.fc !== 4) err("reg.fc.invalid", path + ".fc", "fc must be 3 or 4");
    if (has(r, "type") && !has(TYPES, r.type)) {
      err("reg.type.invalid", path + ".type", "type must be one of " + Object.keys(TYPES).join(" "));
    }
    for (const k of ["word_order", "byte_order"]) {
      if (has(r, k) && !ORDERS.includes(r[k])) err("reg.order.invalid", path + "." + k, k + " must be big or little");
    }
    for (const k of ["scale", "offset"]) {
      if (has(r, k) && !isNum(r[k])) err("reg.number.invalid", path + "." + k, k + " must be a finite number");
    }
    if (has(r, "scale") && isNum(r.scale) && r.scale === 0) {
      err("reg.scale.zero", path + ".scale", "scale of 0 would zero every reading");
    }
  }

  function resolveReg(r, defaults) {
    const out = {};
    for (const k of Object.keys(REG_DEFAULTS)) {
      out[k] = has(r, k) ? r[k] : (has(defaults, k) ? defaults[k] : REG_DEFAULTS[k]);
    }
    return out;
  }

  function telemetryBudget(regs) {
    return 140 + regs.reduce((n, r) => n + r.key.length + 16, 0);
  }

  // -> [{level: "error"|"warn", code, path, msg}]. No `error` == usable.
  function validate(profile, maxRegs) {
    maxRegs = maxRegs || MAX_REGS;
    const iss = [];
    const err = (c, p, m) => iss.push(issue("error", c, p, m));
    const warn = (c, p, m) => iss.push(issue("warn", c, p, m));

    if (!isObj(profile)) { err("profile.type", "", "profile must be an object"); return iss; }

    if (profile.schema !== SCHEMA) err("schema.unsupported", "schema", "schema must be " + SCHEMA);
    if (typeof profile.id !== "string" || !ID_RE.test(profile.id)) {
      err("id.invalid", "id", "id must match [a-z0-9][a-z0-9_-]{0,23}");
    }
    if (typeof profile.name !== "string" || !profile.name.trim()) err("name.missing", "name", "name is required");
    else if (profile.name.length > 48) err("name.long", "name", "name is longer than 48 characters");
    for (const [k, lim] of [["vendor", 48], ["model", 48], ["notes", 200]]) {
      if (has(profile, k) && (typeof profile[k] !== "string" || profile[k].length > lim)) {
        err("text.invalid", k, k + " must be a string of at most " + lim + " characters");
      }
    }
    if (has(profile, "rev") && !(isInt(profile.rev) && profile.rev >= 0 && profile.rev <= 65535)) {
      err("rev.invalid", "rev", "rev must be an integer 0..65535");
    }
    if (has(profile, "transport") && profile.transport !== "tcp" && profile.transport !== "rtu") {
      err("transport.invalid", "transport", "transport must be tcp or rtu");
    }

    const timing = has(profile, "timing") ? profile.timing : {};
    if (!isObj(timing)) err("timing.invalid", "timing", "timing must be an object");
    else {
      for (const [k, [lo, hi]] of Object.entries(TIMING_RANGES)) {
        if (has(timing, k) && !(isInt(timing[k]) && timing[k] >= lo && timing[k] <= hi)) {
          err("timing.range", "timing." + k, k + " must be an integer " + lo + ".." + hi);
        }
      }
      const t = Object.assign({}, TIMING_DEFAULTS, timing);
      if (isInt(t.timeout_ms) && isInt(t.retries) && t.timeout_ms * (t.retries + 1) > MAX_REQUEST_MS) {
        err("timing.budget", "timing", "timeout_ms x (retries + 1) must not exceed " + MAX_REQUEST_MS + " ms");
      }
    }

    let defaults = has(profile, "defaults") ? profile.defaults : {};
    if (!isObj(defaults)) { err("defaults.invalid", "defaults", "defaults must be an object"); defaults = {}; }
    else checkRegFields(defaults, "defaults", err);

    let regs = profile.registers;
    if (!Array.isArray(regs) || !regs.length) { err("registers.missing", "registers", "at least one register is required"); regs = []; }
    else if (regs.length > maxRegs) err("registers.toomany", "registers", "at most " + maxRegs + " registers");

    const seen = new Map();
    const spans = [];
    regs.forEach((r, i) => {
      const path = "registers[" + i + "]";
      if (!isObj(r)) { err("reg.type", path, "register must be an object"); return; }
      const key = r.key;
      if (typeof key !== "string" || !KEY_RE.test(key)) err("reg.key.invalid", path + ".key", "key must match [A-Za-z0-9_]{1,31}");
      else if (seen.has(key)) err("reg.key.duplicate", path + ".key", "duplicate key " + key);
      else seen.set(key, i);
      checkRegFields(r, path, err);
      const res = resolveReg(r, defaults);
      const addr = r.address;
      if (!isInt(addr) || addr < 0 || addr > 65535) err("reg.address.range", path + ".address", "address must be an integer 0..65535");
      else if (has(TYPES, res.type)) {
        if (addr + TYPES[res.type][0] > 65536) err("reg.address.range", path + ".address", "register runs past address 65535");
        else spans.push([res.fc, addr, addr + TYPES[res.type][0], key, i]);
      }
      for (const [k, lim] of [["unit", 8], ["label", 40], ["group", 24]]) {
        if (has(r, k) && (typeof r[k] !== "string" || r[k].length > lim)) {
          err("text.invalid", path + "." + k, k + " must be a string of at most " + lim + " characters");
        }
      }
      if (has(r, "decimals") && !(isInt(r.decimals) && r.decimals >= 0 && r.decimals <= 6)) {
        err("reg.decimals", path + ".decimals", "decimals must be an integer 0..6");
      }
    });

    // Partial overlap is almost always a wrong address or type; identical spans are fine.
    spans.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] ||
      (a[3] < b[3] ? -1 : a[3] > b[3] ? 1 : 0) || a[4] - b[4]);
    for (let a = 0; a < spans.length; a++) {
      for (let b = a + 1; b < spans.length; b++) {
        const [fa, sa, ea, ka] = spans[a];
        const [fb, sb, eb, kb, ib] = spans[b];
        if (fb !== fa || sb >= ea) break;
        if (sa !== sb || ea !== eb) warn("reg.overlap", "registers[" + ib + "]", kb + " partly overlaps " + ka + "; check address or type");
      }
    }

    const views = has(profile, "views") ? profile.views : [];
    if (!Array.isArray(views)) err("views.invalid", "views", "views must be an array");
    else {
      if (views.length > MAX_VIEWS) err("views.toomany", "views", "at most " + MAX_VIEWS + " views");
      const vids = new Set();
      views.forEach((w, i) => {
        const path = "views[" + i + "]";
        if (!isObj(w)) { err("view.type", path, "view must be an object"); return; }
        if (typeof w.id !== "string" || !VIEW_ID_RE.test(w.id)) err("view.id.invalid", path + ".id", "view id must match [A-Za-z0-9][A-Za-z0-9_-]{0,23}");
        else if (vids.has(w.id)) err("view.id.duplicate", path + ".id", "duplicate view id " + w.id);
        else vids.add(w.id);
        if (has(w, "label") && (typeof w.label !== "string" || w.label.length > 24)) {
          err("text.invalid", path + ".label", "label must be a string of at most 24 characters");
        }
        const keys = w.keys;
        if (!Array.isArray(keys) || !keys.length) { err("view.keys.missing", path + ".keys", "a view needs at least one key"); return; }
        if (keys.length > MAX_VIEW_KEYS) err("view.keys.toomany", path + ".keys", "at most " + MAX_VIEW_KEYS + " keys");
        for (const k of keys) if (!seen.has(k)) err("view.keys.unknown", path + ".keys", "unknown register key " + k);
      });
    }

    if (regs.length && regs.every(r => isObj(r) && typeof r.key === "string")) {
      if (telemetryBudget(regs) > 2000) warn("telemetry.large", "registers", "telemetry frame may exceed 2000 bytes");
    }
    if (canonicalJson(profile).length > MAX_BLOB) err("blob.toolarge", "", "profile JSON exceeds " + MAX_BLOB + " bytes");
    return iss;
  }

  const errorsOf = iss => iss.filter(i => i.level === "error");

  // ---------------------------------------------------------------- resolve
  // -> {timing, regs}. Every register carries key, address, fc, type, word_order,
  // byte_order, scale, offset, decimals: exactly what a gateway needs.
  function resolve(profile) {
    const timing = Object.assign({}, TIMING_DEFAULTS, profile.timing || {});
    const defaults = profile.defaults || {};
    const regs = profile.registers.map(r => {
      const d = resolveReg(r, defaults);
      d.key = r.key;
      d.address = r.address;
      if (has(r, "decimals")) d.decimals = r.decimals;
      else d.decimals = (d.type === "f32" || d.type === "f64" || d.scale !== 1) ? 3 : 0;
      return d;
    });
    return { timing, regs };
  }

  // ----------------------------------------------------------------- decode
  const swap16 = w => ((w & 0xFF) << 8) | (w >> 8);

  function rawBits(words, type, wordOrder, byteOrder) {
    const n = TYPES[type][0];
    if (words.length !== n) throw new Error(type + " needs " + n + " words");
    let ws = byteOrder === "little" ? words.map(swap16) : words.slice();
    if (wordOrder === "little") ws.reverse();
    let v = 0n;
    for (const w of ws) v = (v << 16n) | BigInt(w);
    return v;
  }

  // -> number, or null for a non-finite float (a failed read).
  function decodeWords(words, type, wordOrder, byteOrder, scale, offset) {
    wordOrder = wordOrder || "big"; byteOrder = byteOrder || "big";
    scale = scale === undefined ? 1 : scale; offset = offset === undefined ? 0 : offset;
    const bits = rawBits(words, type, wordOrder, byteOrder);
    let raw;
    const signed = (b, width) => Number(BigInt.asIntN(width, b));
    switch (type) {
      case "u16": case "u32": case "u64": raw = Number(bits); break;
      case "i16": raw = signed(bits, 16); break;
      case "i32": raw = signed(bits, 32); break;
      case "i64": raw = signed(bits, 64); break;
      case "f32": {
        const dv = new DataView(new ArrayBuffer(4));
        dv.setUint32(0, Number(bits));
        raw = dv.getFloat32(0);
        break;
      }
      default: {
        const dv = new DataView(new ArrayBuffer(8));
        dv.setBigUint64(0, bits);
        raw = dv.getFloat64(0);
      }
    }
    if ((type === "f32" || type === "f64") && !Number.isFinite(raw)) return null;
    return raw * scale + offset;
  }

  // The inverse, for the simulator and tests.
  function encodeValue(value, type, wordOrder, byteOrder, scale, offset) {
    wordOrder = wordOrder || "big"; byteOrder = byteOrder || "big";
    scale = scale === undefined ? 1 : scale; offset = offset === undefined ? 0 : offset;
    const raw = (value - offset) / scale;
    const n = TYPES[type][0];
    let bits;
    if (type === "f32") {
      const dv = new DataView(new ArrayBuffer(4)); dv.setFloat32(0, raw); bits = BigInt(dv.getUint32(0));
    } else if (type === "f64") {
      const dv = new DataView(new ArrayBuffer(8)); dv.setFloat64(0, raw); bits = dv.getBigUint64(0);
    } else {
      const w = BigInt(n * 16);
      let r = BigInt(Math.round(raw));
      if (type[0] === "i") {
        const lo = -(1n << (w - 1n)), hi = (1n << (w - 1n)) - 1n;
        r = r < lo ? lo : r > hi ? hi : r;
      } else {
        const hi = (1n << w) - 1n;
        r = r < 0n ? 0n : r > hi ? hi : r;
      }
      bits = BigInt.asUintN(Number(w), r);
    }
    let ws = [];
    for (let i = 0; i < n; i++) ws.push(Number((bits >> BigInt(16 * (n - 1 - i))) & 0xFFFFn));
    if (wordOrder === "little") ws.reverse();
    if (byteOrder === "little") ws = ws.map(swap16);
    return ws;
  }

  const formatValue = (v, decimals) => v.toFixed(decimals);

  // ------------------------------------------------------------------- plan
  // -> [[fc, start, words, [indexes]]]
  function planBlocks(regs, maxBlock) {
    const order = regs.map((_, i) => i).sort((a, b) =>
      regs[a].fc - regs[b].fc || regs[a].address - regs[b].address || a - b);
    const blocks = [];
    for (const i of order) {
      const r = regs[i];
      const end = r.address + TYPES[r.type][0];
      if (blocks.length) {
        const b = blocks[blocks.length - 1];
        if (b.fc === r.fc && r.address <= b.end && Math.max(b.end, end) - b.start <= maxBlock) {
          b.end = Math.max(b.end, end);
          b.idx.push(i);
          continue;
        }
      }
      blocks.push({ fc: r.fc, start: r.address, end, idx: [i] });
    }
    return blocks.map(b => [b.fc, b.start, b.end - b.start, b.idx]);
  }

  // ------------------------------------------------------------------- wire
  function wireName(name) {
    const bytes = new TextEncoder().encode(name).slice(0, 44);
    return new TextDecoder("utf-8", { fatal: false }).decode(bytes).replace(/�+$/, "");
  }

  // -> [[action, args]] that upload `profile` to a gateway, in order.
  function wireCommands(profile) {
    const p = normalize(profile);
    const { timing, regs } = resolve(p);
    const blob = canonicalJson(p);
    const cmds = [["profile_begin", {
      id: p.id, name: wireName(p.name), rev: p.rev, n: regs.length, blob_len: blob.length,
      gap: timing.read_gap_ms, tmo: timing.timeout_ms, blk: timing.max_block, retries: timing.retries,
    }]];
    for (let i = 0; i < regs.length; i += REGS_PER_CHUNK) {
      cmds.push(["profile_regs", {
        id: p.id, i,
        regs: regs.slice(i, i + REGS_PER_CHUNK).map(r => ({
          k: r.key, a: r.address, f: r.fc, t: r.type, w: r.word_order, b: r.byte_order,
          s: r.scale, o: r.offset, d: r.decimals,
        })),
      }]);
    }
    for (let off = 0; off < blob.length; off += META_CHUNK) {
      cmds.push(["profile_meta", { id: p.id, off, data: blob.slice(off, off + META_CHUNK) }]);
    }
    cmds.push(["profile_commit", { id: p.id }]);
    return cmds;
  }

  // ---------------------------------------------------------------- helpers
  // Tiles for a view. A profile without views gets one page with every register.
  function viewsOf(profile) {
    if (profile && Array.isArray(profile.views) && profile.views.length) return profile.views;
    return [{ id: "all", label: "all", keys: (profile ? profile.registers : []).map(r => r.key) }];
  }

  function newProfile() {
    return {
      schema: SCHEMA, id: "", name: "", rev: 1, transport: "tcp",
      timing: Object.assign({}, TIMING_DEFAULTS),
      defaults: Object.assign({}, REG_DEFAULTS),
      registers: [], views: [],
    };
  }

  // "Voltage L1" -> "Voltage_L1"; always a legal key.
  function makeKey(text, taken) {
    // Letters that NFKD does not decompose (Turkish dotless i, German sharp s, ...).
    const odd = { "\u0131": "i", "\u0130": "I", "\u00df": "ss", "\u0142": "l", "\u0141": "L",
      "\u00f8": "o", "\u00d8": "O", "\u0111": "d", "\u0110": "D", "\u00e6": "ae", "\u00c6": "AE" };
    let k = String(text || "").replace(/[\u0130\u0131\u00df\u0141\u0142\u00d8\u00f8\u0110\u0111\u00c6\u00e6]/g, c => odd[c])
      .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
      .replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 31);
    if (!k) k = "Reg";
    let out = k, n = 2;
    while (taken && taken.has(out)) { const suffix = "_" + n++; out = k.slice(0, 31 - suffix.length) + suffix; }
    return out;
  }

  return {
    SCHEMA, MAX_REGS, MAX_VIEWS, MAX_VIEW_KEYS, MAX_PROFILES, MAX_BLOB, MAX_REQUEST_MS,
    REGS_PER_CHUNK, META_CHUNK, TYPES, ORDERS, TIMING_DEFAULTS, TIMING_RANGES, REG_DEFAULTS,
    ID_RE, KEY_RE,
    canonicalJson, normalize, validate, errorsOf, resolve, resolveReg,
    decodeWords, encodeValue, formatValue, planBlocks, wireCommands, wireName, telemetryBudget,
    viewsOf, newProfile, makeKey,
  };
});
