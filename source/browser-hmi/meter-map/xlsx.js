// Excel (.xlsx) -> tables, one per sheet. Same ZIP container as .docx.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./zip.js"));
  else root.OsosXlsx = factory(root.OsosZip);
})(typeof self !== "undefined" ? self : this, function (Zip) {
  "use strict";

  const ENT = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
  const dec = s => s.replace(/&(#x[0-9a-f]+|#[0-9]+|[a-z]+);/gi, (m, e) =>
    e[0] === "#" ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10))
      : (ENT[e.toLowerCase()] !== undefined ? ENT[e.toLowerCase()] : m));

  const colIndex = ref => {
    const letters = /^[A-Z]+/.exec(ref);
    if (!letters) return 0;
    let n = 0;
    for (const ch of letters[0]) n = n * 26 + (ch.charCodeAt(0) - 64);
    return n - 1;
  };

  function sharedStrings(xml) {
    if (!xml) return [];
    return [...xml.matchAll(/<si>([\s\S]*?)<\/si>/g)].map(m =>
      dec([...m[1].matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map(t => t[1]).join("")));
  }

  function sheetRows(xml, strings) {
    const rows = [];
    for (const r of xml.matchAll(/<row[^>]*>([\s\S]*?)<\/row>/g)) {
      const cells = [];
      for (const c of r[1].matchAll(/<c ([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
        const ref = /r="([A-Z]+\d+)"/.exec(c[1]);
        const type = /t="(\w+)"/.exec(c[1]);
        const body = c[2] || "";
        const v = /<v>([\s\S]*?)<\/v>/.exec(body);
        let text = "";
        if (type && type[1] === "s" && v) text = strings[parseInt(v[1], 10)] || "";
        else if (type && type[1] === "inlineStr") text = dec([...body.matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map(t => t[1]).join(""));
        else if (v) text = dec(v[1]);
        const idx = ref ? colIndex(ref[1]) : cells.length;
        while (cells.length < idx) cells.push("");
        cells[idx] = text.replace(/\s+/g, " ").trim();
      }
      rows.push(cells);
    }
    return rows;
  }

  async function parseXlsx(bytes) {
    const entries = Zip.listEntries(bytes);
    const strings = sharedStrings(await Zip.readText(entries, "xl/sharedStrings.xml"));
    const names = [...entries.keys()].filter(n => /^xl\/worksheets\/sheet\d+\.xml$/.test(n))
      .sort((a, b) => parseInt(a.match(/\d+/)[0], 10) - parseInt(b.match(/\d+/)[0], 10));
    if (!names.length) throw new Error("This does not look like an Excel .xlsx file (no worksheets).");
    const tables = [];
    for (const n of names) {
      const rows = sheetRows(await Zip.readText(entries, n), strings);
      if (rows.length) tables.push({ rows, context: [] });
    }
    return { tables, paragraphs: [] };
  }

  return { parseXlsx, sheetRows };
});
