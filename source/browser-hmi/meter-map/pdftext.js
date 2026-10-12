// PDF -> lines of cells, using PDF.js (vendor/pdf.min.js).
//
// PDF has no tables, only text fragments at coordinates. This groups fragments
// into lines by their vertical position, then into cells by the gaps between
// them, and keeps each cell's x position so columns can be recovered even when a
// row leaves a cell empty. A scanned PDF (pictures of text) has no text layer:
// that is reported, not guessed at.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.OsosPdfText = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // fragments: [{ str, x, y, w, h }] for one page -> lines [{ y, cells: [{ x, end, text }] }]
  function groupLines(items) {
    const frags = items.filter(i => i.str && i.str.trim() !== "")
      .sort((a, b) => (b.y - a.y) || (a.x - b.x));
    const lines = [];
    for (const f of frags) {
      const tol = Math.max(2, f.h * 0.5);
      let line = lines.length ? lines[lines.length - 1] : null;
      if (!line || Math.abs(line.y - f.y) > tol) {
        line = { y: f.y, items: [] };
        lines.push(line);
      }
      line.items.push(f);
    }
    return lines.map(line => {
      const items = line.items.sort((a, b) => a.x - b.x);
      const cells = [];
      for (const f of items) {
        const last = cells[cells.length - 1];
        const gap = last ? f.x - last.end : Infinity;
        const em = Math.max(f.h, 6);
        if (last && gap < em * 0.25) { last.text += f.str; last.end = f.x + f.w; }            // same word
        else if (last && gap < em * 1.2) { last.text += " " + f.str; last.end = f.x + f.w; }  // same cell
        else cells.push({ x: f.x, end: f.x + f.w, text: f.str });
      }
      for (const c of cells) c.text = c.text.replace(/\s+/g, " ").trim();
      return { y: line.y, cells: cells.filter(c => c.text) };
    }).filter(l => l.cells.length);
  }

  // pdfjsLib is injected: the page's global in a browser, the vendored build in Node.
  // -> { lines: [{ page, y, cells: [{x, end, text}] }], pages, hasText }
  async function extractLines(pdfjsLib, bytes) {
    const task = pdfjsLib.getDocument({
      data: bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes),
      isEvalSupported: false, useSystemFonts: false, verbosity: 0,
    });
    const doc = await task.promise;
    const lines = [];
    let chars = 0;
    for (let p = 1; p <= doc.numPages; p++) {
      const page = await doc.getPage(p);
      const content = await page.getTextContent();
      const items = content.items.filter(i => typeof i.str === "string").map(i => ({
        str: i.str, x: i.transform[4], y: i.transform[5], w: i.width || 0,
        h: Math.abs(i.height || i.transform[3] || 8),
      }));
      for (const l of groupLines(items)) {
        lines.push({ page: p, y: l.y, cells: l.cells });
        chars += l.cells.reduce((n, c) => n + c.text.length, 0);
      }
    }
    const pages = doc.numPages;
    await doc.destroy();
    return { lines, pages, hasText: chars > 20 };
  }

  return { extractLines, groupLines };
});
