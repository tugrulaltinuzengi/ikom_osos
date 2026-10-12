// Word (.docx) -> tables and paragraphs.
//
// A .docx is a ZIP whose word/document.xml holds the text. Register maps are
// nearly always Word tables, so this reads <w:tbl> into rows of cell strings,
// keeping the paragraphs before each table as context ("Input registers, FC04").
// No DOM is needed (Node has none): the XML is walked with a small tokenizer that
// knows only the handful of tags involved.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./zip.js"));
  else root.OsosDocx = factory(root.OsosZip);
})(typeof self !== "undefined" ? self : this, function (Zip) {
  "use strict";

  const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
  const decode = s => s.replace(/&(#x[0-9a-f]+|#[0-9]+|[a-z]+);/gi, (m, e) => {
    if (e[0] === "#") {
      const cp = e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(cp) ? String.fromCodePoint(cp) : m;
    }
    return ENTITIES[e.toLowerCase()] !== undefined ? ENTITIES[e.toLowerCase()] : m;
  });

  function* tokens(xml) {
    const re = /<(\/?)([A-Za-z0-9:_-]+)([^>]*?)(\/?)>|([^<]+)/g;
    let m;
    while ((m = re.exec(xml))) {
      if (m[5] !== undefined) { yield { type: "text", text: m[5] }; continue; }
      const attrs = {};
      m[3].replace(/([A-Za-z0-9:_-]+)="([^"]*)"/g, (_, k, v) => { attrs[k] = v; return ""; });
      yield { type: m[1] ? "close" : m[4] ? "self" : "open", name: m[2], attrs };
    }
  }

  const clean = s => s.replace(/\s+/g, " ").trim();

  // -> { tables: [{ rows: string[][], context: string[] }], paragraphs: string[] }
  function parseDocumentXml(xml) {
    const tables = [];
    const paragraphs = [];
    let depth = 0;                  // table nesting; only the outermost level is a table
    let table = null, row = null, cell = null, para = null;
    let inText = false;
    const recent = [];              // paragraphs seen since the last table

    for (const t of tokens(xml)) {
      if (t.type === "text") {
        if (inText && para !== null) para += t.text;
        continue;
      }
      const name = t.name;
      if (t.type === "open" || t.type === "self") {
        if (name === "w:tbl") {
          depth++;
          if (depth === 1) table = { rows: [], context: recent.slice(-3) };
        } else if (name === "w:tr" && depth === 1) row = [];
        else if (name === "w:tc" && depth === 1) cell = { text: [], span: 1, vmerge: null };
        else if (name === "w:gridSpan" && cell) cell.span = parseInt(t.attrs["w:val"], 10) || 1;
        else if (name === "w:vMerge" && cell) cell.vmerge = t.attrs["w:val"] === "restart" ? "restart" : "continue";
        else if (name === "w:p") para = "";
        else if (name === "w:t") inText = t.type === "open";
        else if ((name === "w:tab" || name === "w:br" || name === "w:noBreakHyphen") && para !== null) {
          para += name === "w:noBreakHyphen" ? "-" : " ";
        }
      } else {  // close
        if (name === "w:t") inText = false;
        else if (name === "w:p" && para !== null) {
          const text = clean(decode(para));
          para = null;
          if (cell) { if (text) cell.text.push(text); }
          else if (depth === 0 && text) { paragraphs.push(text); recent.push(text); }
        } else if (name === "w:tc" && depth === 1 && row && cell) {
          row.push(cell);
          cell = null;
        } else if (name === "w:tr" && depth === 1 && table && row) {
          table.rows.push(row);
          row = null;
        } else if (name === "w:tbl") {
          depth--;
          if (depth === 0 && table) {
            tables.push(finishTable(table));
            table = null;
            recent.length = 0;
          }
        }
      }
    }
    return { tables, paragraphs };
  }

  // Expand merged cells to a rectangular grid of strings.
  function finishTable(table) {
    const rows = [];
    table.rows.forEach((cells, r) => {
      const out = [];
      for (const c of cells) {
        let text = clean(c.text.join(" "));
        if (c.vmerge === "continue" && rows[r - 1]) text = rows[r - 1][out.length] || "";
        out.push(text);
        for (let k = 1; k < c.span; k++) out.push("");
      }
      rows.push(out);
    });
    return { rows, context: table.context };
  }

  async function parseDocx(bytes) {
    const entries = Zip.listEntries(bytes);
    const xml = await Zip.readText(entries, "word/document.xml");
    if (xml === null) throw new Error("This does not look like a Word .docx file (no word/document.xml).");
    return parseDocumentXml(xml);
  }

  return { parseDocx, parseDocumentXml };
});
