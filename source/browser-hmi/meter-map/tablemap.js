// Register-table heuristics: rows of text -> a draft meter profile.
//
// Pure functions, no I/O, no DOM. Input is what docx.js / pdftext.js / a CSV split
// produce; output is a list of draft registers, each carrying a confidence and the
// notes that explain it, so the review screen can show a person exactly what was
// guessed. Nothing here is trusted blindly: the editor always sits between this
// and the gateway.
//
// Handles English and Turkish headers, 4xxxx/3xxxx register notation, hex and
// decimal addresses, "x10" / "/10" / "0.1" scales, decimal commas, and merged
// cells. See tests/tablemap.test.js for the cases it is held to.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./profile.js"));
  else root.OsosTableMap = factory(root.OsosProfile);
})(typeof self !== "undefined" ? self : this, function (P) {
  "use strict";

  // ------------------------------------------------------------------ text
  // Lower case, diacritics folded (Turkish dotless i included), single spaces.
  function fold(s) {
    return String(s == null ? "" : s).replace(/İ/g, "i").replace(/I/g, "i").toLowerCase()
      .replace(/ı/g, "i").normalize("NFKD").replace(/[̀-ͯ]/g, "")
      .replace(/\s+/g, " ").trim();
  }

  // ---------------------------------------------------------------- headers
  // Role vocabularies, matched against the folded header cell.
  const ROLES = [
    ["address", /^(modbus )?(reg(ister)?s?\.?( ?(addr(ess)?|no\.?|number|#|adr))?|addr(ess)?(es)?( \(.*\))?|adres(i)?( ?\(.*\))?|offset|reg\.? ?adr(es)?i?|pdu( address)?|adr\.?|address ?\(.*\)|register address.*|parameter address|reg ?(\(hex\)|\(dec\)))$/],
    ["name", /^(parameter( name)?s?|name|description|desc\.?|signal|variable|measurement|measured value|quantity|item|function name|tanim|aciklama|parametre( adi)?|isim|ad|adi|olcum|deger adi|data( name)?|point|tag)$/],
    ["type", /^(data ?type|type|format|data format|value type|variable type|veri ?tipi|tip|veri formati|datatype)$/],
    ["unit", /^(unit|units|uom|birim|eng\.? unit)$/],
    ["scale", /^(scale|scaling|multiplier|multiply|factor|scale factor|resolution|gain|coefficient|divisor|carpan|katsayi|cozunurlukle?|olcek|conversion|step|lsb)$/],
    ["length", /^(length|size|qty|quantity|words|no\.? of (reg(ister)?s?|words)|number of (reg(ister)?s?|words)|count|reg(ister)?s? count|adet|uzunluk|word count|# ?regs?)$/],
    ["access", /^(access|r\/w|rw|read\/write|mode|erisim|read|write|r\/w access)$/],
    ["fc", /^(fc|func|function|function code|modbus function|fonksiyon( kodu)?|command|cmd)$/],
  ];

  function roleOf(cell) {
    const f = fold(cell);
    if (!f) return null;
    for (const [role, re] of ROLES) if (re.test(f)) return role;
    // looser: a longer header that contains the keyword ("Register address (decimal)")
    if (/^(register|reg\.?|modbus) ?(address|addr|no)\b/.test(f) || /\baddress\b/.test(f)) return "address";
    if (/\bdata ?type\b|\bveri ?tipi\b/.test(f)) return "type";
    if (/\b(description|parameter|parametre|aciklama|tanim)\b/.test(f)) return "name";
    if (/\b(multiplier|scale|scaling|resolution|carpan|katsayi|factor)\b/.test(f)) return "scale";
    if (/\bunit\b|\bbirim\b/.test(f)) return "unit";
    if (/\bfunction code\b|\bfc\b/.test(f)) return "fc";
    if (/\b(number of|no\.? of) (registers|words)\b|\blength\b|\bsize\b/.test(f)) return "length";
    if (/\baccess\b|\bread\/write\b|\br\/w\b/.test(f)) return "access";
    return null;
  }

  // -> { roles: { address: colIndex, ... }, score } when the row looks like a header.
  function headerRow(cells) {
    const roles = {};
    let score = 0;
    cells.forEach((c, i) => {
      const r = roleOf(c);
      if (r && roles[r] === undefined) { roles[r] = i; score++; }
    });
    const ok = score >= 2 && (roles.address !== undefined || roles.name !== undefined) &&
      (roles.address !== undefined || roles.type !== undefined || roles.unit !== undefined);
    return ok ? { roles, score } : null;
  }

  // ---------------------------------------------------------------- address
  // -> { address, fc, length, notation, ok } for one address cell.
  //    notation: "hex" | "modbus" (3xxxx/4xxxx) | "dec"
  function parseAddress(text) {
    const t = String(text || "").replace(/[ \s]+/g, " ").trim();
    if (!t) return { ok: false };
    // explicit hex wins: "0x0010", "0010h", "(0x10)"
    const hexes = [...t.matchAll(/0x([0-9a-f]{1,4})\b|\b([0-9a-f]{1,4})h\b/gi)];
    if (hexes.length) {
      const first = parseInt(hexes[0][1] || hexes[0][2], 16);
      let length = 0;
      if (hexes.length > 1) {
        const last = parseInt(hexes[hexes.length - 1][1] || hexes[hexes.length - 1][2], 16);
        if (last >= first && last - first < 8) length = last - first + 1;
      }
      return { ok: true, address: first, notation: "hex", length, raw: t };
    }
    const nums = [...t.matchAll(/\d+/g)].map(m => m[0]);
    if (!nums.length) return { ok: false };
    // a trailing word is fine ("40001 Hi"), but letters mixed into a number are not an address
    if (/[a-z]/i.test(t.replace(/\b(hi|lo|high|low|msw|lsw|word)\b/gi, ""))) {
      if (!/^\s*\d+\s*(?:[-–—~]|\.\.|to)\s*\d+\s*$/i.test(t) && !/^\s*\d+\s*$/.test(t)) return { ok: false };
    }
    const v = parseInt(nums[0], 10);
    const second = nums.length > 1 ? parseInt(nums[1], 10) : NaN;
    const rangeLen = Number.isFinite(second) && second >= v && second - v < 8 ? second - v + 1 : 0;
    return { ok: true, address: v, notation: "dec", length: rangeLen, raw: t };
  }

  // 30001.. / 40001.. (and the 6-digit 300001.. / 400001..) mean "register N of the
  // table", not a PDU address: 40001 is holding register 0.
  function modbusNotation(v) {
    if (v >= 30001 && v <= 39999) return { fc: 4, address: v - 30001 };
    if (v >= 40001 && v <= 49999) return { fc: 3, address: v - 40001 };
    if (v >= 300001 && v <= 365536) return { fc: 4, address: v - 300001 };
    if (v >= 400001 && v <= 465536) return { fc: 3, address: v - 400001 };
    return null;
  }

  // ------------------------------------------------------------------- type
  // Order matters: "unsigned" contains "signed", "uint" contains "int".
  const TYPE_RULES = [
    [/float ?64|double|real ?64|lreal|\bf64\b/, "f64"],
    [/float|real|single|ieee|\bf32\b|\bflt\b/, "f32"],
    [/u ?int ?64|unsigned ?(int(eger)? ?)?64|\bu64\b|qword|ulong ?long|uint64/, "u64"],
    [/\b(s|i)? ?int ?64|signed ?(int(eger)? ?)?64|\bi64\b|\bs64\b|long ?long|sint64/, "i64"],
    [/u ?int ?32|unsigned ?(int(eger)? ?|long ?)?32|\bu32\b|dword|udint|unsigned ?long|\bulong\b|uint32/, "u32"],
    [/\b(s|i)? ?int ?32|signed ?(int(eger)? ?|long ?)?32|\bi32\b|\bs32\b|\bdint\b|\blong\b|sint32/, "i32"],
    [/u ?int ?16|unsigned ?(int(eger)? ?|short ?|word ?)?(16)?|\bu16\b|\bword\b|\busint\b|\bushort\b|uint16|\buint\b/, "u16"],
    [/\b(s|i)? ?int ?16|signed ?(int(eger)? ?|short ?)?16|\bi16\b|\bs16\b|\bshort\b|\bint(eger)?\b|\bsint\b|tamsayi/, "i16"],
    [/\bbool(ean)?\b|\bbit\b|\bstatus\b|\bflag\b/, "bool"],
  ];

  function parseType(text) {
    const f = fold(text).replace(/[_-]/g, "");
    if (!f) return null;
    for (const [re, t] of TYPE_RULES) if (re.test(f)) return t;
    return null;
  }

  // ------------------------------------------------------------------ scale
  // -> { scale, note, doubt } ; scale is the multiplier the profile needs.
  function parseScale(text, headerFold) {
    const raw = String(text == null ? "" : text).trim();
    if (!raw || /^[-–—\/n\.a]+$/i.test(raw)) return null;
    const f = raw.replace(/×|✕|⨯/g, "x").replace(/÷/g, "/").replace(",", ".").replace(/\s+/g, "");
    const num = s => { const n = parseFloat(s); return Number.isFinite(n) ? n : null; };
    let m;
    if ((m = /^(?:x|\*)(\d*\.?\d+)$/i.exec(f))) {                       // x10  : raw is 10x the value
      const n = num(m[1]);
      return n ? { scale: 1 / n, note: `"${raw}" read as raw = value x ${m[1]}, so scale 1/${m[1]}`, doubt: false } : null;
    }
    if ((m = /^(?:\/|:)(\d*\.?\d+)$/.exec(f))) {                        // /10  : divide the raw count
      const n = num(m[1]);
      return n ? { scale: 1 / n, note: `"${raw}" read as divide by ${m[1]}`, doubt: false } : null;
    }
    if ((m = /^1\/(\d*\.?\d+)$/.exec(f))) {
      const n = num(m[1]);
      return n ? { scale: 1 / n, note: `"${raw}" read as 1/${m[1]}`, doubt: false } : null;
    }
    if ((m = /^(\d*\.?\d+)(?:e([+-]?\d+))?$/i.exec(f))) {               // bare number
      const n = num(f);
      if (!n) return null;
      if (n === 1) return null;
      const divisor = /divisor|bolen/.test(headerFold || "");
      if (divisor) return { scale: 1 / n, note: `"${raw}" is a divisor`, doubt: false };
      if (n < 1) return { scale: n, note: "", doubt: false };
      // 10, 100, 1000: manuals disagree on whether this multiplies or divides
      return { scale: 1 / n, note: `"${raw}" read as divide by ${raw}; if the meter means multiply, set scale ${raw}`, doubt: true };
    }
    return null;
  }

  function decimalsFor(scale) {
    if (!scale || scale >= 1) return undefined;
    const d = Math.min(6, Math.max(0, Math.round(-Math.log10(scale))));
    return d || undefined;
  }

  // ------------------------------------------------------------------- unit
  const UNIT_ALIASES = {
    v: "V", volt: "V", volts: "V", a: "A", amp: "A", amps: "A", ampere: "A", amper: "A",
    hz: "Hz", hertz: "Hz", w: "W", watt: "W", kw: "kW", mw: "MW", va: "VA", kva: "kVA",
    var: "var", kvar: "kvar", varh: "varh", kvarh: "kvarh", wh: "Wh", kwh: "kWh", mwh: "MWh",
    "%": "%", c: "C", degc: "C", "°c": "C", s: "s", sec: "s", sn: "s", ms: "ms", min: "min",
    h: "h", ohm: "ohm", "ω": "ohm", rpm: "rpm", bar: "bar", pf: "", cos: "",
  };
  function parseUnit(text) {
    const f = fold(text).replace(/[\[\]()]/g, "").trim();
    if (!f) return "";
    if (Object.prototype.hasOwnProperty.call(UNIT_ALIASES, f)) return UNIT_ALIASES[f];
    return f.length <= 8 && /^[\w%\/.°]+$/.test(f) ? text.replace(/[\[\]()]/g, "").trim() : "";
  }
  // "Voltage L1 (V)" / "Current [A]" -> unit, and the name without it
  function splitNameUnit(name) {
    const m = /^(.*?)[\s]*[\[(]\s*([^\])]{1,8})\s*[\])]\s*$/.exec(name);
    if (m) {
      const u = parseUnit(m[2]);
      if (u) return { name: m[1].trim(), unit: u };
    }
    return { name: name.trim(), unit: "" };
  }

  // --------------------------------------------------------------- doc hints
  // Word order / function code hints found anywhere in the document text.
  function documentHints(texts) {
    const all = fold(texts.join(" \n "));
    const hints = { wordOrder: null, byteOrder: null, fc: null, notes: [] };
    if (/\bcdab\b|low word first|lsw first|word[- ]?swap|swapped word|little[- ]endian word/.test(all)) {
      hints.wordOrder = "little"; hints.byteOrder = "big"; hints.notes.push("document mentions CDAB / low word first");
    } else if (/\bdcba\b/.test(all)) {
      hints.wordOrder = "little"; hints.byteOrder = "little"; hints.notes.push("document mentions DCBA");
    } else if (/\bbadc\b|byte[- ]?swap/.test(all)) {
      hints.wordOrder = "big"; hints.byteOrder = "little"; hints.notes.push("document mentions BADC / byte swap");
    } else if (/\babcd\b|big[- ]endian|high word first|msw first|most significant word first|yuksek word/.test(all)) {
      hints.wordOrder = "big"; hints.byteOrder = "big"; hints.notes.push("document mentions ABCD / big endian");
    }
    const inp = /input regist|giris regist|function code 0?4\b|\bfc ?0?4\b|fonksiyon 0?4\b/.test(all);
    const hold = /holding regist|tutma regist|function code 0?3\b|\bfc ?0?3\b|fonksiyon 0?3\b/.test(all);
    if (inp && !hold) hints.fc = 4;
    else if (hold && !inp) hints.fc = 3;
    return hints;
  }

  function tableFcHint(contextLines) {
    const c = fold((contextLines || []).join(" "));
    if (/input regist|giris regist|function code 0?4\b|\bfc ?0?4\b|fonksiyon 0?4\b|\b3x\b/.test(c)) return 4;
    if (/holding regist|tutma regist|function code 0?3\b|\bfc ?0?3\b|fonksiyon 0?3\b|\b4x\b/.test(c)) return 3;
    return null;
  }

  // -------------------------------------------------------------- extraction
  const isSkipName = s => /^(reserved|rezerve|spare|not used|unused|kullanilmiyor|---?)$/.test(fold(s));

  // One table -> rows. `table` = { rows: string[][], context: string[] }.
  // opts: { base: "auto"|0|1, default32: "f32"|"u32"|"i32", fc, wordOrder }
  function extractTable(table, opts, tableNo) {
    opts = opts || {};
    const rows = table.rows.filter(r => r.some(c => String(c).trim() !== ""));
    let hdrIdx = -1, hdr = null;
    for (let i = 0; i < Math.min(rows.length, 6); i++) {
      const h = headerRow(rows[i]);
      if (h && (!hdr || h.score > hdr.score)) { hdr = h; hdrIdx = i; }
    }
    const warnings = [];
    let roles;
    let body;
    if (hdr) { roles = hdr.roles; body = rows.slice(hdrIdx + 1); }
    else {
      // no header: the address column is the one whose cells most often parse as addresses
      body = rows;
      const width = Math.max(...rows.map(r => r.length), 0);
      let best = -1, bestN = 0;
      for (let c = 0; c < width; c++) {
        const n = rows.filter(r => parseAddress(r[c]).ok).length;
        if (n > bestN) { bestN = n; best = c; }
      }
      if (best < 0 || bestN < 2) return { rows: [], warnings: [] };
      roles = { address: best };
      // name = the longest-text column that is not the address
      let nameCol = -1, nameLen = 0;
      for (let c = 0; c < width; c++) {
        if (c === best) continue;
        const len = rows.reduce((n, r) => n + String(r[c] || "").length, 0);
        if (len > nameLen) { nameLen = len; nameCol = c; }
      }
      if (nameCol >= 0) roles.name = nameCol;
      warnings.push(`table ${tableNo}: no header row, columns guessed (address = column ${best + 1})`);
    }
    if (roles.address === undefined) return { rows: [], warnings: [`table ${tableNo}: no address column`] };

    const headerFold = k => (hdr && roles[k] !== undefined) ? fold(rows[hdrIdx][roles[k]]) : "";
    const parsed = body.map(r => ({ cells: r, addr: parseAddress(r[roles.address]) }));
    // Is this table written in 3xxxx/4xxxx notation? Decide for the whole table.
    const decs = parsed.filter(p => p.addr.ok && p.addr.notation === "dec").map(p => p.addr.address);
    const modbusN = decs.filter(v => modbusNotation(v)).length;
    const notation = decs.length >= 2 && modbusN / decs.length >= 0.8;
    const minDec = decs.length ? Math.min(...decs) : null;
    const fcHint = opts.fc || tableFcHint(table.context) || null;
    const out = [];

    parsed.forEach((p, ri) => {
      const cells = p.cells;
      const cell = k => roles[k] === undefined ? "" : String(cells[roles[k]] == null ? "" : cells[roles[k]]).trim();
      const notes = [];
      let confidence = "high";
      const src = `table ${tableNo}, row ${hdr ? hdrIdx + 2 + ri : ri + 1}`;
      if (!p.addr.ok) return;

      let { address } = p.addr;
      let fc = null;
      if (p.addr.notation === "dec" && notation) {
        const m = modbusNotation(address);
        if (!m) { notes.push("address outside the 3xxxx/4xxxx ranges"); confidence = "low"; }
        else { address = m.address; fc = m.fc; notes.push(`${p.addr.raw} is register notation: address ${address}, function code ${fc}`); }
      } else if (p.addr.notation === "dec") {
        const base = opts.base === undefined ? "auto" : opts.base;
        if (base === 1) address -= 1;
        else if (base === "auto" && minDec === 1 && address >= 1) {
          notes.push("table starts at 1: addresses may be counted from 1 (use 'subtract 1' if the test read fails)");
          confidence = "medium";
        }
        if (address < 0) { notes.push("address below 0 after the base shift"); confidence = "low"; address = 0; }
      }
      if (address > 65535) { notes.push("address above 65535"); confidence = "low"; address = 65535; }

      // function code: explicit column, then notation, then table hint
      const fcCell = cell("fc");
      let m;
      if (fcCell && (m = /0?([34])\b/.exec(fcCell.replace(/fc|0x/gi, "")))) fc = parseInt(m[1], 10);
      if (fc === null && fcHint) fc = fcHint;

      let name = cell("name");
      const split = splitNameUnit(name);
      name = split.name;
      if (!name || isSkipName(name)) { if (isSkipName(name)) return; notes.push("no parameter name"); confidence = "low"; }

      // access: skip write-only rows
      const acc = fold(cell("access"));
      if (acc && /^(w|wo|write|write only|yazma)$/.test(acc)) return;

      let type = parseType(cell("type"));
      const lenCell = parseInt(cell("length"), 10);
      let length = Number.isFinite(lenCell) ? lenCell : (p.addr.length || 0);
      if (type === "bool") { type = "u16"; notes.push("bit/boolean value read as a 16-bit register"); confidence = "medium"; }
      if (!type) {
        confidence = confidence === "high" ? "medium" : confidence;
        if (length === 1) type = "u16";
        else if (length === 2) type = opts.default32 || "f32";
        else if (length === 4) type = "u64";
        else { type = opts.default32 || "f32"; }
        notes.push(`type not stated${length ? ` (length ${length})` : ""}: assumed ${type}`);
      } else if (length && P.TYPES[type] && P.TYPES[type][0] !== length) {
        notes.push(`type ${type} is ${P.TYPES[type][0]} word(s) but the table says ${length}`);
        confidence = "low";
      }

      const sc = parseScale(cell("scale"), headerFold("scale"));
      let scale = 1;
      if (sc) {
        scale = sc.scale;
        if (sc.note) notes.push(sc.note);
        if (sc.doubt && confidence === "high") confidence = "medium";
      }
      let unit = parseUnit(cell("unit")) || split.unit;

      const row = {
        include: true,
        key: "", label: name.slice(0, 40), address, fc: fc || (opts.fc || 3), type,
        scale, offset: 0, unit, confidence, notes, source: src,
      };
      if (!fc) { row.fcGuessed = true; }
      const dec = decimalsFor(scale);
      if (dec !== undefined) row.decimals = dec;
      out.push(row);
    });

    if (out.length && minDec === 1 && !notation && (opts.base === undefined || opts.base === "auto")) {
      warnings.push(`table ${tableNo}: addresses start at 1. Many manuals count registers from 1; if reads come back wrong, subtract 1 from every address.`);
    }
    return { rows: out, warnings, roles, hasHeader: !!hdr };
  }

  // PDF lines -> tables. A header row starts a table; the nearest text above it is
  // its context. Cells are assigned to header columns by x position, so an empty
  // cell does not shift the rest of the row.
  function pdfTables(lines) {
    const tables = [];
    let cur = null;
    let context = [];
    for (const line of lines) {
      const texts = line.cells.map(c => c.text);
      const h = line.cells.length >= 2 ? headerRow(texts) : null;
      if (h) {
        cur = { rows: [], context: context.slice(-3), cols: line.cells.map(c => ({ x: c.x, end: c.end })), roles: h.roles };
        cur.rows.push(texts.slice());
        // keep the header row aligned to its own columns
        tables.push(cur);
        context = [];
        continue;
      }
      if (cur && line.cells.length >= 2) {
        const row = new Array(cur.cols.length).fill("");
        for (const c of line.cells) {
          let col = 0;
          for (let i = 0; i < cur.cols.length; i++) {
            const next = cur.cols[i + 1];
            const bound = next ? (cur.cols[i].end < next.x ? (cur.cols[i].end + next.x) / 2 : next.x - 1) : Infinity;
            if (c.x < bound) { col = i; break; }
            col = Math.min(i + 1, cur.cols.length - 1);
          }
          row[col] = row[col] ? row[col] + " " + c.text : c.text;
        }
        cur.rows.push(row);
      } else {
        context.push(texts.join(" "));
        if (context.length > 6) context.shift();
        // text between tables ends the table only when it is a sentence, not a row fragment
        if (cur && texts.join(" ").length > 60) cur = null;
      }
    }
    return tables;
  }

  // CSV / TSV text -> one table
  function delimited(text) {
    const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter(l => l.trim() !== "");
    if (!lines.length) return [];
    const count = (l, ch) => (l.match(new RegExp(ch === "\t" ? "\t" : "\\" + ch, "g")) || []).length;
    const sample = lines.slice(0, 10);
    let best = ",", bestN = -1;
    for (const ch of [",", ";", "\t", "|"]) {
      const n = sample.reduce((s, l) => s + count(l, ch), 0);
      if (n > bestN) { bestN = n; best = ch; }
    }
    // No delimiter at all (text pasted from a PDF): columns are separated by runs of spaces.
    const rows = bestN > 0 ? lines.map(l => splitCsvLine(l, best))
      : lines.map(l => l.trim().split(/\s{2,}/));
    return [{ rows, context: [] }];
  }
  function splitCsvLine(line, d) {
    const out = [];
    let cur = "", q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (q) {
        if (ch === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; }
        else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === d) { out.push(cur.trim()); cur = ""; }
      else cur += ch;
    }
    out.push(cur.trim());
    return out;
  }

  // ------------------------------------------------------------------ driver
  // doc = { tables, paragraphs? , lines? } -> { rows, warnings, hints }
  function extract(doc, opts) {
    opts = opts || {};
    const tables = doc.tables ? doc.tables.slice() : [];
    if (doc.lines) tables.push(...pdfTables(doc.lines));
    const texts = (doc.paragraphs || []).concat(tables.flatMap(t => t.context || []));
    if (doc.lines) texts.push(...doc.lines.map(l => l.cells.map(c => c.text).join(" ")));
    const hints = documentHints(texts);
    const rows = [];
    const warnings = [];
    tables.forEach((t, i) => {
      const r = extractTable(t, Object.assign({}, opts, { fc: opts.fc || undefined }), i + 1);
      warnings.push(...r.warnings);
      // fall back to the document-wide function code hint only when the table had none
      for (const row of r.rows) {
        if (row.fcGuessed && hints.fc && !opts.fc) { row.fc = hints.fc; }
        delete row.fcGuessed;
        rows.push(row);
      }
    });
    // keys: unique, legal, derived from the label
    const taken = new Set();
    for (const row of rows) {
      row.key = P.makeKey(row.label || ("R" + row.address), taken);
      taken.add(row.key);
    }
    // identical (fc, address) twice: keep the first, drop the rest with a note
    const seen = new Map();
    for (const row of rows) {
      const k = row.fc + ":" + row.address + ":" + row.type;
      if (seen.has(k)) {
        row.include = false;
        row.notes.push(`same register as ${seen.get(k)}; left out`);
      } else seen.set(k, row.key);
    }
    if (!rows.length) warnings.push("No register table found. Check the file, or add registers by hand.");
    const wide = rows.filter(r => P.TYPES[r.type] && P.TYPES[r.type][0] > 1 && r.include);
    if (wide.length && !hints.wordOrder) {
      warnings.push("Word order for 32-bit values is not stated in the document: ABCD (high word first) assumed. Use Test read; if values look wrong, switch to CDAB.");
    }
    return { rows, warnings, hints };
  }

  // Draft rows -> a profile ready for the editor.
  // meta: { id, name, hints, merge, wordOrder, byteOrder }
  function buildProfile(rows, meta) {
    meta = meta || {};
    const inc = rows.filter(r => r.include !== false);
    const mode = arr => {
      const c = new Map();
      for (const v of arr) c.set(v, (c.get(v) || 0) + 1);
      let best = null, n = -1;
      for (const [v, k] of c) if (k > n) { best = v; n = k; }
      return best;
    };
    const defaults = {
      fc: mode(inc.map(r => r.fc)) || 3,
      type: mode(inc.map(r => r.type)) || "f32",
      word_order: meta.wordOrder || (meta.hints && meta.hints.wordOrder) || "big",
      byte_order: meta.byteOrder || (meta.hints && meta.hints.byteOrder) || "big",
      scale: 1, offset: 0,
    };
    const regs = inc.map(r => {
      const o = { key: r.key, address: r.address };
      if (r.fc !== defaults.fc) o.fc = r.fc;
      if (r.type !== defaults.type) o.type = r.type;
      if (r.scale !== 1) o.scale = r.scale;
      if (r.offset) o.offset = r.offset;
      if (r.decimals !== undefined) o.decimals = r.decimals;
      if (r.unit) o.unit = r.unit.slice(0, 8);
      if (r.label) o.label = r.label.slice(0, 40);
      return o;
    });
    const p = P.newProfile();
    p.id = meta.id || "";
    p.name = (meta.name || "").slice(0, 48);
    p.defaults = defaults;
    p.registers = regs;
    p.timing = Object.assign({}, P.TIMING_DEFAULTS);
    if (meta.merge) p.timing.max_block = 16;
    // Tile pages of 12, so a phone screen shows one page without scrolling forever.
    p.views = [];
    for (let i = 0; i < regs.length && p.views.length < P.MAX_VIEWS; i += 12) {
      const keys = regs.slice(i, i + 12).map(r => r.key);
      p.views.push(regs.length <= 12
        ? { id: "all", label: "all", keys }
        : { id: "p" + (p.views.length + 1), label: "page " + (p.views.length + 1), keys });
    }
    return P.normalize(p);
  }

  return {
    fold, roleOf, headerRow, parseAddress, modbusNotation, parseType, parseScale, parseUnit,
    splitNameUnit, documentHints, tableFcHint, extractTable, pdfTables, delimited, splitCsvLine,
    extract, buildProfile, decimalsFor,
  };
});
