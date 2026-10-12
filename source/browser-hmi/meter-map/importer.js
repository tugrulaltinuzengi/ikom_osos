// Upload a register-map document -> a draft profile for review.
//
//   const doc = await OsosImporter.readDocument({ name, bytes }, { pdfjsLib });
//   const draft = OsosImporter.analyze(doc, { default32: "f32" });
//   const profile = OsosImporter.toProfile(draft.rows, { id, name, hints: draft.hints });
//
// Word, Excel, PDF and delimited text are read in the page (or the Android
// WebView). The file is never sent anywhere.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./profile.js"), require("./tablemap.js"), require("./docx.js"),
      require("./xlsx.js"), require("./pdftext.js"));
  } else {
    root.OsosImporter = factory(root.OsosProfile, root.OsosTableMap, root.OsosDocx, root.OsosXlsx, root.OsosPdfText);
  }
})(typeof self !== "undefined" ? self : this, function (P, TM, Docx, Xlsx, PdfText) {
  "use strict";

  const MAX_BYTES = 25 * 1024 * 1024;

  const ext = name => (/\.([A-Za-z0-9]+)$/.exec(name || "") || [, ""])[1].toLowerCase();

  // -> { kind, tables?, lines?, paragraphs?, warnings }
  async function readDocument(file, deps) {
    const bytes = file.bytes instanceof Uint8Array ? file.bytes : new Uint8Array(file.bytes);
    if (bytes.length > MAX_BYTES) throw new Error("That file is larger than 25 MB.");
    const e = ext(file.name);
    if (e === "docx" || e === "dotx" || e === "docm") {
      return Object.assign({ kind: "word", warnings: [] }, await Docx.parseDocx(bytes));
    }
    if (e === "doc") throw new Error("Old Word .doc files cannot be read. In Word, use Save As > .docx (or PDF), then upload that.");
    if (e === "xlsx" || e === "xlsm") {
      return Object.assign({ kind: "excel", warnings: [] }, await Xlsx.parseXlsx(bytes));
    }
    if (e === "xls") throw new Error("Old Excel .xls files cannot be read. Save as .xlsx or CSV, then upload that.");
    if (e === "pdf") {
      const lib = deps && deps.pdfjsLib;
      if (!lib) throw new Error("PDF reading is not available in this page.");
      const r = await PdfText.extractLines(lib, bytes.slice());
      if (!r.hasText) {
        throw new Error("This PDF has no text layer (it looks scanned). Run OCR on it first, or copy the register table into a CSV.");
      }
      return { kind: "pdf", lines: r.lines, pages: r.pages, tables: [], paragraphs: [], warnings: [] };
    }
    if (e === "csv" || e === "tsv" || e === "txt" || e === "") {
      const text = new TextDecoder("utf-8").decode(bytes);
      return { kind: "text", tables: TM.delimited(text), paragraphs: [], warnings: [] };
    }
    throw new Error("Unsupported file type ." + e + ". Use Word (.docx), Excel (.xlsx), PDF, or CSV.");
  }

  // -> { rows, warnings, hints }
  function analyze(doc, opts) {
    const r = TM.extract(doc, opts);
    r.warnings = (doc.warnings || []).concat(r.warnings);
    return r;
  }

  function toProfile(rows, meta) {
    const p = TM.buildProfile(rows, meta);
    return p;
  }

  // An id for a file name: "ACME EM-100 manual.pdf" -> "acme-em-100-manual"
  function idFromName(name) {
    const base = String(name || "").replace(/\.[A-Za-z0-9]+$/, "");
    const id = TM.fold(base).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24).replace(/-+$/, "");
    return /^[a-z0-9]/.test(id) ? id : "meter";
  }

  return { readDocument, analyze, toProfile, idFromName, MAX_BYTES };
});
