"use strict";
// Main HMI page against a v2 modem: tiles must follow the published meter profile.
//   NODE_PATH=$(npm root -g) node tests/hmi_smoke.js
const http = require("node:http"), fs = require("node:fs"), path = require("node:path");
const { chromium } = require("playwright");
const ROOT = path.join(__dirname, "..", "..");
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };
(async () => {
  const srv = http.createServer((req, res) => {
    const f = path.join(ROOT, decodeURIComponent(req.url.split("?")[0]));
    if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "content-type": MIME[path.extname(f)] || "application/octet-stream" });
    fs.createReadStream(f).pipe(res);
  }).listen(0, "127.0.0.1");
  await new Promise(r => srv.on("listening", r));
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.addInitScript(() => {
    const handlers = {};
    window.__sent = [];
    window.mqtt = { connect() {
      const c = { on(ev, f) { handlers[ev] = f; }, subscribe(t) { window.__subs = t; }, publish(t, p) { window.__sent.push([t, p]); } };
      setTimeout(() => handlers.connect && handlers.connect(), 10);
      window.__deliver = (t, p) => handlers.message(t, { toString: () => p });
      return c;
    } };
  });
  await page.route("**/mqtt.min.js", r => r.fulfill({ body: "", contentType: "text/javascript" }));
  await page.goto(`http://127.0.0.1:${srv.address().port}/index.html?modem=gw-01`);
  await page.waitForFunction(() => window.__subs);
  let ok = true;
  const check = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) ok = false; };
  check((await page.evaluate(() => window.__subs)).includes("osos/m/gw-01/a/+/profile"), "subscribes to the profile topic");
  check((await page.getAttribute("#mapLink", "href")).includes("modem=gw-01"), "link to the meter map keeps the modem");
  const prof = { schema: 1, id: "p", name: "P", registers: [{ key: "Pw", address: 0, unit: "W", label: "Active power", decimals: 1 }, { key: "E", address: 2, unit: "kWh" }], views: [{ id: "main", label: "main", keys: ["Pw", "E"] }] };
  await page.evaluate(p => { window.__deliver("osos/m/gw-01/a/an-01/profile", JSON.stringify(p)); window.__deliver("osos/m/gw-01/a/an-01/telemetry", JSON.stringify({ seq: 1, ts: "t", meter_ok: true, values: { Pw: 3800.26, E: null } })); }, prof);
  const text = await page.textContent("#tiles");
  check(text.includes("Active power") && text.includes("3800.3") && text.includes("W"), "tile uses the profile's label, unit and decimals");
  check(text.includes("—"), "null shows as a dash");
  check((await page.textContent("#viewtabs")).trim() === "main", "tabs are the profile's pages");
  await page.evaluate(() => window.__deliver("osos/m/gw-01/a/an-01/profile", ""));
  check((await page.textContent("#viewtabs")).includes("overview"), "a cleared profile falls back to the DKM-440 pages");
  check(errors.length === 0, "no page errors " + errors.join("|"));
  await browser.close(); srv.close();
  process.exit(ok ? 0 : 1);
})();
