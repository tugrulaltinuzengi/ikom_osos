"use strict";
// Runs the shared vectors (source/meter-profiles/vectors.json) through the JS port.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const P = require("../profile.js");

const PROFILES = path.join(__dirname, "..", "..", "..", "meter-profiles");
const VEC = JSON.parse(fs.readFileSync(path.join(PROFILES, "vectors.json"), "utf8"));
const load = f => JSON.parse(fs.readFileSync(path.join(PROFILES, f), "utf8"));

test("decode vectors", () => {
  for (const c of VEC.decode) {
    const got = P.decodeWords(c.words, c.type, c.word_order, c.byte_order, c.scale, c.offset);
    if (c.expect === null) assert.equal(got, null, c.name);
    else assert.ok(Math.abs(got - c.expect) <= 1e-9 * Math.abs(c.expect) + 1e-9, `${c.name}: ${got} vs ${c.expect}`);
  }
});

test("validation vectors", () => {
  for (const c of VEC.validate) {
    const iss = P.validate(c.profile);
    const codes = lvl => [...new Set(iss.filter(i => i.level === lvl).map(i => i.code))].sort();
    assert.deepEqual(codes("error"), c.errors, c.name);
    assert.deepEqual(codes("warn"), c.warns, c.name);
  }
});

test("shipped profiles validate cleanly", () => {
  for (const f of ["dkm440.json", "examples/sdm630.json", "examples/generic-int-scaled.json"]) {
    assert.deepEqual(P.validate(load(f)), [], f);
  }
});

test("plan vectors", () => {
  for (const c of VEC.plan) {
    assert.deepEqual(P.planBlocks(c.regs, c.max_block), c.blocks, c.name);
  }
});

test("wire commands are byte-identical to the Python reference", () => {
  for (const [name, w] of Object.entries(VEC.wire)) {
    const got = P.wireCommands(load(w.file)).map(([action, args]) => ({ action, args }));
    assert.deepEqual(got, w.commands, name);
  }
});

test("every wire message fits the gateway buffer", () => {
  for (const w of Object.values(VEC.wire)) {
    for (const c of w.commands) {
      const msg = JSON.stringify({ id: "c-xxxxxxxx", action: c.action, args: c.args });
      assert.ok(msg.length < 1400, `${c.action}: ${msg.length}`);
    }
  }
});

test("canonical JSON is compact and ASCII", () => {
  assert.equal(P.canonicalJson({ a: "café €", b: [1, 2.5, null, true] }),
    '{"a":"caf\\u00e9 \\u20ac","b":[1,2.5,null,true]}');
  assert.equal(P.canonicalJson({ d: "\u007f" }), '{"d":"\\u007f"}');
});

test("normalize orders keys and drops unknown ones", () => {
  const p = P.normalize({ registers: [{ address: 1, key: "A", zzz: 1 }], name: "n", id: "x", junk: 1 });
  assert.deepEqual(Object.keys(p), ["schema", "id", "name", "rev", "registers"]);
  assert.deepEqual(Object.keys(p.registers[0]), ["key", "address"]);
});

test("encode is the inverse of decode, for every type and byte layout", () => {
  const cases = [["u16", 1234], ["i16", -321], ["u32", 123456], ["i32", -123456], ["f32", 26.5],
    ["u64", 1e12], ["i64", -1e12], ["f64", 1.25]];
  for (const [t, v] of cases) {
    for (const w of P.ORDERS) for (const b of P.ORDERS) {
      const words = P.encodeValue(v, t, w, b);
      assert.equal(words.length, P.TYPES[t][0]);
      assert.ok(Math.abs(P.decodeWords(words, t, w, b) - v) < 1e-6, `${t} ${w} ${b}`);
    }
  }
  assert.deepEqual(P.encodeValue(26.5, "f32", "big", "big"), [0x41D4, 0]);
  assert.deepEqual(P.encodeValue(26.5, "f32", "little", "little"), [0, 0xD441]);
  assert.deepEqual(P.encodeValue(230.5, "u16", "big", "big", 0.1), [2305]);
  assert.deepEqual(P.encodeValue(1e9, "u16"), [0xFFFF]);
  assert.deepEqual(P.encodeValue(-1e9, "i16"), [0x8000]);
});

test("wireName cuts on a character boundary", () => {
  assert.equal(P.wireName("DATAKOM DKM-440"), "DATAKOM DKM-440");
  const long = "é".repeat(40);                    // 80 bytes of UTF-8
  const cut = P.wireName(long);
  assert.equal(new TextEncoder().encode(cut).length, 44);
  assert.ok(!cut.includes("�"));
});

test("makeKey always produces a legal, unique key", () => {
  const taken = new Set(["Voltage_L1"]);
  assert.equal(P.makeKey("Voltage L1", taken), "Voltage_L1_2");
  assert.equal(P.makeKey("Gerilim (V) – L1"), "Gerilim_V_L1");
  assert.equal(P.makeKey("   "), "Reg");
  assert.equal(P.makeKey("Ak\u0131m L1"), "Akim_L1");                       // dotless i
  assert.equal(P.makeKey("\u015eebeke gerilimi"), "Sebeke_gerilimi");
  assert.equal(P.makeKey("x".repeat(60)).length, 31);
  for (const s of ["a b", "Çok yüksek", "1st", "ß"]) assert.match(P.makeKey(s), P.KEY_RE);
});

test("viewsOf falls back to one page with every register", () => {
  const p = load("examples/generic-int-scaled.json");
  assert.equal(P.viewsOf(p)[0].id, "overview");
  const v = P.viewsOf({ registers: [{ key: "A" }, { key: "B" }] });
  assert.deepEqual(v, [{ id: "all", label: "all", keys: ["A", "B"] }]);
});
