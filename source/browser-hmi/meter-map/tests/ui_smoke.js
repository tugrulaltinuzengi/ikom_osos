"use strict";
// Drives the real page in headless Chromium against the in-memory mock gateway.
//
//   NODE_PATH=$(npm root -g) node tests/ui_smoke.js [--shots DIR]
//
// Not part of `node --test` because it needs Playwright and a browser; CI runs the
// pure-logic suites. Exits non-zero on the first failed expectation.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..", "..");          // browser-hmi/
const FIX = path.join(__dirname, "fixtures");
const shotsDir = process.argv.includes("--shots") ? process.argv[process.argv.indexOf("--shots") + 1] : null;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

function serve() {
  return new Promise(resolve => {
    const srv = http.createServer((req, res) => {
      const f = path.join(ROOT, decodeURIComponent(req.url.split("?")[0]));
      if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { "content-type": MIME[path.extname(f)] || "application/octet-stream" });
      fs.createReadStream(f).pipe(res);
    }).listen(0, "127.0.0.1", () => resolve(srv));
  });
}

let failures = 0;
function check(cond, msg) {
  if (cond) console.log("  ok   " + msg);
  else { failures++; console.log("  FAIL " + msg); }
}

(async () => {
  const srv = await serve();
  const base = `http://127.0.0.1:${srv.address().port}/meter-map/index.html`;
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push("pageerror: " + e.message));
  page.on("console", m => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push("console: " + m.text()); });

  // The mock gateway is injected before the page's own scripts run.
  await page.addInitScript({ content: fs.readFileSync(path.join(__dirname, "mockgateway.js"), "utf8") });
  await page.addInitScript(() => {
    window.__mem = {};
    window.__f32 = (fc, addr, v) => {
      const dv = new DataView(new ArrayBuffer(4)); dv.setFloat32(0, v);
      window.__mem[fc + ":" + addr] = dv.getUint16(0); window.__mem[fc + ":" + (addr + 1)] = dv.getUint16(2);
    };
    window.__f32(4, 0, 230.5); window.__f32(3, 260, 26.5);
    window.OsosTransportOverride = () => {
      const gw = new window.MockGateway({
        builtin: window.OSOS_SHIPPED[0],
        meter: (fc, addr, words) => {
          const out = [];
          for (let i = 0; i < words; i++) { const w = window.__mem[fc + ":" + (addr + i)]; if (w === undefined) return null; out.push(w); }
          return out;
        },
      });
      const subs = [], states = [];
      window.__gw = gw;
      const emit = (topic, text) => subs.forEach(f => f(topic, text));
      window.__emit = emit;
      return {
        kind: "mock",
        onMessage(cb) { subs.push(cb); }, onState(cb) { states.push(cb); },
        connect() { states.forEach(f => f(true)); gw.initialMessages().forEach(([t, x]) => emit(t, x)); },
        async send(mid, action, args) {
          const r = gw.handle({ id: "x", action, args });
          for (const [t, x] of r.publish) setTimeout(() => emit(t, x), 5);
          await new Promise(r2 => setTimeout(r2, 5));
          return r.ack;
        },
      };
    };
  });

  const shot = async name => { if (shotsDir) await page.screenshot({ path: path.join(shotsDir, name + ".png"), fullPage: true }); };

  console.log("page load");
  await page.goto(base);
  await page.waitForSelector("#modemsel option[value='gw-01']", { state: 'attached' });
  check((await page.textContent("#connpill")).includes("connected"), "transport connected");
  check((await page.textContent("#targetinfo")).includes("an-01 reads as dkm440"), "target shows the assigned profile");
  await shot("01-profile-empty");

  console.log("examples and validation");
  await page.selectOption("#libsel", "x:sdm630");
  check(await page.locator("#regtable tbody tr").count() === 16, "SDM630 example loaded with 16 registers");
  check((await page.textContent("#issues")).includes("No problems"), "no validation problems");
  check(await page.inputValue("#p-id") === "sdm630", "id bound to the field");
  check(await page.inputValue("#d-fc") === "4", "default function code is 04");
  await page.fill("#regtable tbody tr:nth-child(2) td.k input", "bad key!");
  await page.waitForFunction(() => document.querySelector("#issues .issue.error"));
  check((await page.textContent("#issues")).includes("key must match"), "bad key is reported");
  await page.fill("#regtable tbody tr:nth-child(2) td.k input", "Voltage_L2");
  await page.waitForFunction(() => !document.querySelector("#issues .issue.error"));
  check(true, "fixing the key clears the error");

  console.log("test read");
  await page.click("#regtable tbody tr:nth-child(1) td.act:nth-last-child(2) button");
  await page.waitForFunction(() => /value=/.test(document.querySelector("#regtable tbody tr td.res").textContent));
  const res = await page.textContent("#regtable tbody tr td.res");
  check(/raw=4366 8000 value=230\.50/.test(res), "row test shows raw words and the decoded value (" + res.trim() + ")");
  await page.click("#regtable tbody tr:nth-child(2) td.act:nth-last-child(2) button");
  await page.waitForFunction(() => /read failed/.test(document.querySelectorAll("#regtable tbody tr td.res")[1].textContent));
  check(true, "an unreadable register is reported");
  await shot("02-profile-sdm630");

  console.log("import a Word document");
  await page.click("#tabs button[data-tab=import]");
  await page.setInputFiles("#docfile", path.join(FIX, "acme-em100.docx"));
  await page.waitForSelector("#import-review:not([hidden])");
  check(await page.locator("#drafttable tbody tr").count() === 10, "10 registers found in the .docx");
  check((await page.textContent("#docstatus")).includes("10 register"), "status line");
  await shot("03-import-docx");
  page.once("dialog", d => d.accept());
  await page.click("#io-use");
  await page.waitForSelector("#tab-profile:not([hidden])");
  check(await page.locator("#regtable tbody tr").count() === 10, "profile created from the draft");
  check(await page.inputValue("#p-id") === "acme-em100", "id taken from the file name");
  check((await page.textContent("#issues")).includes("No problems"), "the created profile validates");

  console.log("import a PDF (PDF.js loads on demand)");
  await page.click("#tabs button[data-tab=import]");
  await page.setInputFiles("#docfile", path.join(FIX, "acme-em100.pdf"));
  await page.waitForFunction(() => /10 register/.test(document.getElementById("docstatus").textContent), null, { timeout: 20000 });
  check(true, "10 registers found in the PDF");
  await page.setInputFiles("#docfile", path.join(FIX, "scanned.pdf"));
  await page.waitForFunction(() => /no text layer/.test(document.getElementById("toast").textContent), null, { timeout: 20000 });
  check(true, "scanned PDF refused with an explanation");
  await page.setInputFiles("#docfile", path.join(FIX, "datakom-tr.csv"));
  await page.waitForFunction(() => /4 register/.test(document.getElementById("docstatus").textContent));
  await page.selectOption("#io-base", "1");
  await page.waitForFunction(() => /4 register/.test(document.getElementById("docstatus").textContent));
  check(true, "CSV read; re-analysed after changing the address base");

  console.log("send to the gateway");
  await page.click("#tabs button[data-tab=profile]");
  await page.selectOption("#libsel", "x:sdm630");
  page.once("dialog", d => d.accept());                      // none expected; harmless
  await page.click("#tabs button[data-tab=gateway]");
  check((await page.textContent("#gwprofiles")).includes("DATAKOM DKM-440"), "gateway lists its built-in profile");
  await page.selectOption("#analyzersel", "an-02");
  await page.click("#send");
  await page.waitForFunction(() => /Done\./.test(document.getElementById("sendlog").textContent), null, { timeout: 15000 });
  check(!!(await page.evaluate(() => window.__gw.stored.has("sdm630"))), "gateway stored the profile");
  check((await page.evaluate(() => window.__gw.assign.get("an-02"))) === "sdm630", "and assigned it to an-02");
  await page.waitForFunction(() => document.getElementById("gwprofiles").textContent.includes("used by an-02"));
  check(true, "the gateway list updates from the retained topic");
  await shot("04-gateway");

  console.log("a refusal is shown, not hidden");
  await page.evaluate(() => { const g = window.__gw; const orig = g.handle.bind(g); g.handle = c => c.action === "profile_meta" ? { ack: { id: c.id, ok: false, detail: "flash write failed" }, publish: [] } : orig(c); });
  await page.click("#tabs button[data-tab=profile]");
  await page.fill("#p-rev", "2");
  await page.click("#tabs button[data-tab=gateway]");
  await page.click("#send");
  await page.waitForFunction(() => /Stopped at profile_meta/.test(document.getElementById("sendlog").textContent));
  check(true, "upload stops at the refused step and says why");

  console.log("live values follow the gateway's profile");
  await page.evaluate(() => {
    const t = { v: 2, ts: "2026-01-01T00:00:00Z", seq: 7, meter_ok: true, profile: "sdm630", profile_rev: 1, values: { Voltage_L1: 230.5, Voltage_L2: null, Energy_Import: 1234.5 } };
    window.__emit("osos/m/gw-01/a/an-02/telemetry", JSON.stringify(t));
  });
  await page.click("#tabs button[data-tab=live]");
  await page.waitForFunction(() => document.querySelectorAll("#livetiles .tile").length > 0);
  const tiles = await page.textContent("#livetiles");
  check(tiles.includes("Voltage L1") && tiles.includes("230.50") && tiles.includes("V"), "labelled tile with unit");
  check(tiles.includes("—"), "a null reading shows as a dash");
  await shot("05-live");

  console.log("untrusted text stays text");
  await page.click("#tabs button[data-tab=profile]");
  await page.fill("#p-name", '<img src=x onerror="window.__pwned=1">');
  await page.fill("#regtable tbody tr:nth-child(1) td.l input", '<b onmouseover="window.__pwned=1">x</b>');
  await page.click("#tabs button[data-tab=gateway]");
  check(!(await page.evaluate(() => window.__pwned)), "markup in names is never interpreted");

  check(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
  srv.close();
  console.log(failures ? `\n${failures} FAILED` : "\nall ok");
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
