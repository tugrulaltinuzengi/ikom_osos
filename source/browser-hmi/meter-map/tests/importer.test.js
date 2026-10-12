"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const P = require("../profile.js");
const TM = require("../tablemap.js");
const Zip = require("../zip.js");
const Docx = require("../docx.js");
const I = require("../importer.js");

// PDF.js (vendored) wants a browser-ish global; keep its Node noise out of the test output.
global.self = global;
const warn = console.warn;
console.warn = () => {};
const pdfjs = require("../vendor/pdf.min.js");
console.warn = warn;
pdfjs.GlobalWorkerOptions.workerSrc = path.join(__dirname, "..", "vendor", "pdf.worker.min.js");

const fx = f => new Uint8Array(fs.readFileSync(path.join(__dirname, "fixtures", f)));
const read = async f => I.readDocument({ name: f, bytes: fx(f) }, { pdfjsLib: pdfjs });
const brief = rows => rows.filter(r => r.include).map(r =>
  [r.key, r.fc, r.address, r.type, r.scale, r.unit]);

// ---------------------------------------------------------------- cell parsers
test("address notation: 3xxxx/4xxxx, hex, ranges, decimals", () => {
  assert.deepEqual(TM.parseAddress("40001"), { ok: true, address: 40001, notation: "dec", length: 0, raw: "40001" });
  assert.equal(TM.parseAddress("0x0010").address, 16);
  assert.equal(TM.parseAddress("0x0010").notation, "hex");
  assert.equal(TM.parseAddress("0010h").address, 16);
  assert.equal(TM.parseAddress("40001 (0x0000)").address, 0);          // explicit hex wins
  const r = TM.parseAddress("0x0004-0x0005");
  assert.equal(r.address, 4); assert.equal(r.length, 2);
  const d = TM.parseAddress("100-101");
  assert.equal(d.address, 100); assert.equal(d.length, 2);
  assert.equal(TM.parseAddress("Voltage").ok, false);
  assert.equal(TM.parseAddress("").ok, false);
  assert.equal(TM.parseAddress("12 volts").ok, false);
  assert.deepEqual(TM.modbusNotation(40001), { fc: 3, address: 0 });
  assert.deepEqual(TM.modbusNotation(30010), { fc: 4, address: 9 });
  assert.deepEqual(TM.modbusNotation(400101), { fc: 3, address: 100 });
  assert.equal(TM.modbusNotation(50000), null);
});

test("data types, English and Turkish, signed and unsigned", () => {
  const cases = {
    "Float32": "f32", "float": "f32", "REAL": "f32", "IEEE 754": "f32", "Float": "f32",
    "double": "f64", "Float64": "f64",
    "UINT16": "u16", "Unsigned 16": "u16", "word": "u16", "unsigned int": "u16", "U16": "u16",
    "INT16": "i16", "short": "i16", "Integer": "i16", "signed 16 bit": "i16", "int": "i16",
    "UINT32": "u32", "DWORD": "u32", "unsigned long": "u32", "u32": "u32",
    "INT32": "i32", "long": "i32", "DINT": "i32", "Signed 32": "i32",
    "UINT64": "u64", "INT64": "i64",
    "bool": "bool", "bit": "bool",
    "": null, "text": null,
  };
  for (const [text, want] of Object.entries(cases)) assert.equal(TM.parseType(text), want, text);
});

test("scales: multiplier, divisor, x10, decimal comma, bare numbers", () => {
  const sc = (t, h) => { const r = TM.parseScale(t, h); return r ? Number(r.scale.toPrecision(12)) : null; };
  assert.equal(sc("0.1"), 0.1);
  assert.equal(sc("0,01"), 0.01);
  assert.equal(sc("x10"), 0.1);
  assert.equal(sc("×100"), 0.01);
  assert.equal(sc("*10"), 0.1);
  assert.equal(sc("/10"), 0.1);
  assert.equal(sc("÷10"), 0.1);
  assert.equal(sc("1/100"), 0.01);
  assert.equal(sc("1"), null);
  assert.equal(sc(""), null);
  assert.equal(sc("-"), null);
  assert.equal(sc("10", "divisor"), 0.1);
  const bare = TM.parseScale("10", "scale");                              // ambiguous: flagged
  assert.equal(bare.scale, 0.1); assert.equal(bare.doubt, true);
});

test("units, including those inside the name", () => {
  assert.equal(TM.parseUnit("volt"), "V");
  assert.equal(TM.parseUnit("kWh"), "kWh");
  assert.equal(TM.parseUnit("°C"), "C");
  assert.equal(TM.parseUnit(""), "");
  assert.deepEqual(TM.splitNameUnit("Voltage L1 (V)"), { name: "Voltage L1", unit: "V" });
  assert.deepEqual(TM.splitNameUnit("Current [A]"), { name: "Current", unit: "A" });
  assert.deepEqual(TM.splitNameUnit("Power factor"), { name: "Power factor", unit: "" });
});

test("header detection: English, Turkish, and rows that are not headers", () => {
  assert.ok(TM.headerRow(["Register", "Description", "Type", "Unit"]));
  assert.ok(TM.headerRow(["Adres", "Parametre", "Birim", "Veri Tipi", "Açıklama"]));
  assert.ok(TM.headerRow(["Reg (hex)", "Parameter", "Data type", "Multiplier", "R/W"]));
  assert.equal(TM.headerRow(["30001", "Voltage L1", "Float32", "V"]), null);
  assert.equal(TM.headerRow(["Modbus register map"]), null);
  assert.equal(TM.headerRow(["Voltage", "Current"]), null);
});

test("document hints: word order and function code", () => {
  assert.equal(TM.documentHints(["32-bit values are CDAB"]).wordOrder, "little");
  assert.equal(TM.documentHints(["low word first"]).wordOrder, "little");
  assert.equal(TM.documentHints(["Big-endian (ABCD)"]).wordOrder, "big");
  assert.equal(TM.documentHints(["DCBA"]).byteOrder, "little");
  assert.equal(TM.documentHints(["nothing relevant"]).wordOrder, null);
  assert.equal(TM.documentHints(["Input registers (function code 04)"]).fc, 4);
  assert.equal(TM.documentHints(["Holding registers, FC03"]).fc, 3);
  assert.equal(TM.documentHints(["Input registers and holding registers"]).fc, null);
});

// ---------------------------------------------------------------------- zip
function storedZip(files) {                    // a tiny ZIP writer, stored entries only
  const enc = new TextEncoder();
  const parts = [], central = [];
  let off = 0;
  const u16 = n => [n & 255, n >> 8 & 255], u32 = n => [n & 255, n >> 8 & 255, n >> 16 & 255, n >>> 24];
  for (const [name, text] of Object.entries(files)) {
    const nb = enc.encode(name), data = enc.encode(text);
    const local = [0x50, 0x4b, 3, 4, ...u16(20), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(0),
      ...u32(data.length), ...u32(data.length), ...u16(nb.length), ...u16(0)];
    parts.push(Uint8Array.from(local), nb, data);
    central.push(Uint8Array.from([0x50, 0x4b, 1, 2, ...u16(20), ...u16(20), ...u16(0), ...u16(0), ...u16(0), ...u16(0),
      ...u32(0), ...u32(data.length), ...u32(data.length), ...u16(nb.length), ...u16(0), ...u16(0), ...u16(0),
      ...u16(0), ...u32(0), ...u32(off)]), nb);
    off += local.length + nb.length + data.length;
  }
  const cd = Buffer.concat(central);
  const eocd = Uint8Array.from([0x50, 0x4b, 5, 6, 0, 0, 0, 0, ...u16(Object.keys(files).length),
    ...u16(Object.keys(files).length), ...u32(cd.length), ...u32(off), 0, 0]);
  return new Uint8Array(Buffer.concat([...parts, cd, eocd]));
}

test("zip: stored entries, deflated entries (real .docx), and garbage", async () => {
  const z = Zip.listEntries(storedZip({ "a.txt": "hello", "dir/b.txt": "wörld" }));
  assert.equal(await Zip.readText(z, "a.txt"), "hello");
  assert.equal(await Zip.readText(z, "dir/b.txt"), "wörld");
  assert.equal(await Zip.readText(z, "missing"), null);
  const real = Zip.listEntries(fx("acme-em100.docx"));          // deflate
  assert.match(await Zip.readText(real, "word/document.xml"), /<w:tbl>/);
  assert.throws(() => Zip.listEntries(new Uint8Array(100)), /ZIP/);
});

// --------------------------------------------------------------------- docx
test("docx XML: merged cells, nested text, entities, context paragraphs", () => {
  const xml = `<w:document><w:body>
    <w:p><w:r><w:t>Input registers (function code 04)</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Address</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Name &amp; unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Type</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>30001</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Volt</w:t></w:r><w:r><w:tab/><w:t>age</w:t></w:r></w:p></w:tc>
            <w:tc><w:tcPr><w:gridSpan w:val="1"/></w:tcPr><w:p><w:r><w:t>Float</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc><w:tc><w:p><w:r><w:t>Second line</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Float</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:p><w:r><w:t>After the table</w:t></w:r></w:p></w:body></w:document>`;
  const d = Docx.parseDocumentXml(xml);
  assert.equal(d.tables.length, 1);
  assert.deepEqual(d.tables[0].rows[0], ["Address", "Name & unit", "Type"]);
  assert.deepEqual(d.tables[0].rows[1], ["30001", "Volt age", "Float"]);
  assert.equal(d.tables[0].rows[2][0], "30001");                       // vertical merge carries down
  assert.deepEqual(d.tables[0].context, ["Input registers (function code 04)"]);
  assert.deepEqual(d.paragraphs, ["Input registers (function code 04)", "After the table"]);
});

// ------------------------------------------------------ whole documents
test("Word document with two tables: notation, hex, scale, units, skips", async () => {
  const doc = await read("acme-em100.docx");
  assert.equal(doc.kind, "word");
  assert.equal(doc.tables.length, 2);
  const r = I.analyze(doc, {});
  assert.deepEqual(brief(r.rows), [
    ["Voltage_L1", 4, 0, "f32", 1, "V"],
    ["Voltage_L2", 4, 2, "f32", 1, "V"],
    ["Voltage_L3", 4, 4, "f32", 1, "V"],
    ["Total_active_power", 4, 6, "f32", 1, "W"],
    ["Frequency", 4, 8, "f32", 1, "Hz"],
    ["Voltage_L1_2", 3, 0, "u16", 0.1, ""],        // same label as table 1: key made unique
    ["Current_L1", 3, 1, "u16", 0.01, ""],
    ["Active_power", 3, 2, "i16", 1, ""],
    ["Temperature", 3, 3, "i16", 0.1, "C"],        // unit lifted out of "(°C)"
    ["Energy_import", 3, 4, "u32", 0.01, ""],      // address range 0x0004-0x0005
  ]);
  assert.equal(r.rows.length, 10);                  // write-only and reserved rows left out entirely
  assert.equal(r.hints.wordOrder, "big");
  assert.ok(r.rows.every(x => x.confidence === "high"));
  assert.deepEqual(r.warnings, []);
});

test("Turkish Word document: Turkish headers, 4xxxx notation, folded keys", async () => {
  const r = I.analyze(await read("datakom-tr.docx"), {});
  assert.deepEqual(brief(r.rows), [
    ["Sebeke_gerilimi_L1", 3, 100, "f32", 1, "V"],
    ["Sebeke_gerilimi_L2", 3, 102, "f32", 1, "V"],
    ["Frekans", 3, 104, "f32", 1, "Hz"],
    ["Guc_faktoru", 3, 106, "f32", 1, ""],
  ]);
  assert.ok(r.rows.every(x => P.KEY_RE.test(x.key)));
});

test("PDF gives the same registers as the Word file, including a row with an empty cell", async () => {
  const doc = await read("acme-em100.pdf");
  assert.equal(doc.kind, "pdf");
  const word = I.analyze(await read("acme-em100.docx"), {});
  const pdf = I.analyze(doc, {});
  assert.deepEqual(brief(pdf.rows), brief(word.rows));
  // "Active power" has no multiplier: its R/W cell must not slide into that column
  const ap = pdf.rows.find(r => r.key === "Active_power");
  assert.equal(ap.scale, 1);
  assert.equal(pdf.hints.wordOrder, "big");
});

test("a PDF without a text layer is refused with an explanation", async () => {
  await assert.rejects(read("scanned.pdf"), /no text layer/);
});

test("Excel and CSV (semicolons, decimal commas, x100)", async () => {
  const x = I.analyze(await read("acme-em100.xlsx"), {});
  assert.deepEqual(brief(x.rows).map(r => r.slice(0, 4)), [
    ["Voltage_L1", 3, 0, "u16"], ["Current_L1", 3, 1, "u16"], ["Active_power", 3, 2, "i16"],
    ["Temperature", 3, 3, "i16"], ["Energy_import", 3, 4, "u32"],
  ]);
  const c = I.analyze(await read("datakom-tr.csv"), {});
  assert.deepEqual(brief(c.rows), [
    ["Gerilim_L1", 3, 0, "u16", 0.1, "V"],
    ["Akim_L1", 3, 1, "u16", 0.01, "A"],
    ["Aktif_guc", 3, 2, "i16", 1, "W"],
    ["Enerji", 3, 3, "u32", 0.01, "kWh"],
  ]);
  assert.ok(c.warnings.some(w => /Word order/.test(w)));              // 32-bit value, order not stated
});

test("unsupported and legacy file types are rejected clearly", async () => {
  const rd = name => I.readDocument({ name, bytes: new Uint8Array(10) }, { pdfjsLib: pdfjs });
  await assert.rejects(rd("map.doc"), /\.docx/);
  await assert.rejects(rd("map.xls"), /\.xlsx/);
  await assert.rejects(rd("map.png"), /Unsupported/);
  await assert.rejects(rd("map.docx"), /ZIP/);
});

// -------------------------------------------------------------- row policies
test("tables without a header, with 1-based addresses, and with an unknown type", () => {
  const t = { context: [], rows: [["1", "Voltage L1"], ["2", "Voltage L2"], ["3", "Current L1"]] };
  const r = TM.extractTable(t, {}, 1);
  assert.equal(r.rows.length, 3);
  assert.ok(r.warnings.some(w => /no header row/.test(w)));
  assert.ok(r.warnings.some(w => /start at 1/.test(w)));
  assert.ok(r.rows.every(x => x.confidence !== "high" && x.type === "f32"));   // type not stated
  const shifted = TM.extractTable(t, { base: 1 }, 1);
  assert.deepEqual(shifted.rows.map(x => x.address), [0, 1, 2]);
});

test("a type that disagrees with the stated length is marked low confidence", () => {
  const t = { context: [], rows: [["Address", "Name", "Type", "Length"], ["100", "Total energy", "UINT16", "2"], ["102", "Voltage", "Float", "2"]] };
  const r = TM.extractTable(t, {}, 1).rows;
  assert.equal(r[0].confidence, "low");
  assert.equal(r[1].confidence, "high");
});

test("a bare scale of 10 is flagged as a guess", () => {
  const t = { context: [], rows: [["Address", "Name", "Type", "Scale"], ["0", "Voltage", "UINT16", "10"]] };
  const r = TM.extractTable(t, {}, 1).rows[0];
  assert.equal(r.scale, 0.1);
  assert.equal(r.confidence, "medium");
  assert.ok(r.notes.some(n => /divide by 10/.test(n)));
});

test("duplicate registers are left out of the draft, not silently kept", () => {
  const doc = { tables: [{ context: [], rows: [["Address", "Name", "Type"], ["0", "A", "UINT16"], ["0", "B", "UINT16"]] }] };
  const r = TM.extract(doc, {});
  assert.deepEqual(r.rows.map(x => x.include), [true, false]);
  assert.ok(r.rows[1].notes.some(n => /same register/.test(n)));
});

// ------------------------------------------------------------- the profile
test("the draft becomes a valid profile that survives the wire format", async () => {
  const draft = I.analyze(await read("acme-em100.docx"), {});
  const profile = I.toProfile(draft.rows, { id: I.idFromName("ACME EM-100 manual.docx"), name: "ACME EM-100", hints: draft.hints });
  assert.equal(profile.id, "acme-em-100-manual");
  assert.deepEqual(P.errorsOf(P.validate(profile)), []);
  // fc 4 is the common one in this document? five rows each: the first mode wins, the rest override
  assert.equal(profile.registers.length, 10);
  const { regs } = P.resolve(profile);
  assert.deepEqual(regs.map(r => [r.key, r.fc, r.address, r.type]).slice(0, 2), [["Voltage_L1", 4, 0, "f32"], ["Voltage_L2", 4, 2, "f32"]]);
  assert.equal(regs.find(r => r.key === "Energy_import").scale, 0.01);
  assert.ok(P.wireCommands(profile).length > 3);
  // views are pages of at most 12 tiles, all naming real keys
  for (const v of profile.views) assert.ok(v.keys.length <= 12);
});

test("idFromName", () => {
  assert.equal(I.idFromName("ACME EM-100 manual.pdf"), "acme-em-100-manual");
  assert.equal(I.idFromName("Çok şey.docx"), "cok-sey");
  assert.equal(I.idFromName("!!!.pdf"), "meter");
  assert.match(I.idFromName("x".repeat(80) + ".pdf"), P.ID_RE);
});
