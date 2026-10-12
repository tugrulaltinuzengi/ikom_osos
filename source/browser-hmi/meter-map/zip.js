// Minimal ZIP reader: enough to open .docx and .xlsx (which are ZIP containers).
// Supports stored (0) and deflate (8) entries. Deflate uses the platform's
// DecompressionStream, so there is nothing to vendor - it exists in every current
// browser, in Android's WebView, and in Node 18+.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.OsosZip = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const u16 = (b, o) => b[o] | (b[o + 1] << 8);
  const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;

  async function inflateRaw(data) {
    if (typeof DecompressionStream === "undefined") {
      throw new Error("This browser cannot unzip Word files. Export the register table to PDF or CSV instead.");
    }
    const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  // -> Map<name, () => Promise<Uint8Array>>  (entries are inflated on demand)
  function listEntries(bytes) {
    // End of central directory: scan back for its signature.
    let eocd = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
      if (u32(bytes, i) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) throw new Error("Not a ZIP/Word file (no central directory).");
    const count = u16(bytes, eocd + 10);
    let p = u32(bytes, eocd + 16);
    const out = new Map();
    for (let n = 0; n < count; n++) {
      if (u32(bytes, p) !== 0x02014b50) throw new Error("Corrupt ZIP directory.");
      const method = u16(bytes, p + 10);
      const csize = u32(bytes, p + 20);
      const nameLen = u16(bytes, p + 28), extraLen = u16(bytes, p + 30), commentLen = u16(bytes, p + 32);
      const local = u32(bytes, p + 42);
      const name = new TextDecoder().decode(bytes.subarray(p + 46, p + 46 + nameLen));
      out.set(name, async () => {
        if (u32(bytes, local) !== 0x04034b50) throw new Error("Corrupt ZIP entry " + name);
        const start = local + 30 + u16(bytes, local + 26) + u16(bytes, local + 28);
        const raw = bytes.subarray(start, start + csize);
        if (method === 0) return raw;
        if (method === 8) return inflateRaw(raw);
        throw new Error("Unsupported ZIP compression method " + method);
      });
      p += 46 + nameLen + extraLen + commentLen;
    }
    return out;
  }

  async function readText(entries, name) {
    const get = entries.get(name);
    if (!get) return null;
    return new TextDecoder("utf-8").decode(await get());
  }

  return { listEntries, readText };
});
