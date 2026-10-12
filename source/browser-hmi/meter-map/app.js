// Meter map page: edit a meter profile, read one out of a manual, send it to a
// gateway. The same files run in the browser HMI and inside the Android app's
// WebView; only transport.js differs.
//
// Everything user- or document-supplied is put on the page with textContent /
// value, never innerHTML: an uploaded manual is untrusted text.
(function () {
  "use strict";

  const P = window.OsosProfile, T = window.OsosTopics, F = window.OsosFleet;
  const U = window.OsosUploader, TM = window.OsosTableMap, I = window.OsosImporter;
  const $ = id => document.getElementById(id);

  // ------------------------------------------------------------------ helpers
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "value") el.value = v;
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const clear = el => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  let toastTimer = null;
  function toast(msg, kind) {
    const el = $("toast");
    el.textContent = msg;
    el.className = "show " + (kind || "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = ""; }, kind === "bad" ? 6000 : 3000);
  }

  function lsGet(key, dflt) {
    try { const v = localStorage.getItem(key); return v === null ? dflt : JSON.parse(v); } catch (e) { return dflt; }
  }
  function lsSet(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); return true; } catch (e) { return false; }
  }

  // -------------------------------------------------------------------- state
  const qs = new URLSearchParams(location.search);
  const S = {
    profile: null,
    savedJson: "",
    idTouched: false,
    tab: "profile",
    fleet: F.create(),
    mid: qs.get("modem") || null,
    aid: qs.get("analyzer") || null,
    connected: false,
    tests: {},               // register index -> {ok, text}
    doc: null, docName: "", draft: null, draftOpts: {},
    liveView: null,
    sending: false, abort: null,
  };
  const LIB_KEY = "osos_meter_profiles_v1";
  const library = {
    all() { return lsGet(LIB_KEY, {}); },
    save(p) { const all = library.all(); all[p.id] = P.normalize(p); return lsSet(LIB_KEY, all); },
    remove(id) { const all = library.all(); delete all[id]; lsSet(LIB_KEY, all); },
  };
  const shipped = () => (window.OSOS_SHIPPED || []).slice();

  // ------------------------------------------------------------ profile model
  function setProfile(p, opts) {
    S.profile = P.normalize(p);
    if (!S.profile.timing) S.profile.timing = Object.assign({}, P.TIMING_DEFAULTS);
    if (!S.profile.defaults) S.profile.defaults = Object.assign({}, P.REG_DEFAULTS);
    if (!S.profile.registers) S.profile.registers = [];
    if (!S.profile.views) S.profile.views = [];
    S.tests = {};
    S.idTouched = !!(opts && opts.keepId) || !!S.profile.id;
    S.savedJson = JSON.stringify(S.profile);
    renderProfile();
  }
  const dirty = () => JSON.stringify(S.profile) !== S.savedJson;
  function confirmDiscard() { return !dirty() || window.confirm("The profile in the editor has unsaved changes. Replace it?"); }

  const touch = debounce(() => { renderIssues(); renderCount(); renderSendInfo(); }, 150);

  // ---------------------------------------------------------------- tab logic
  function showTab(name) {
    S.tab = name;
    for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("active", b.dataset.tab === name);
    for (const el of document.querySelectorAll(".tabpane")) el.hidden = el.id !== "tab-" + name;
    if (name === "gateway") renderGateway();
    if (name === "live") renderLive();
  }
  $("tabs").addEventListener("click", e => { if (e.target.dataset && e.target.dataset.tab) showTab(e.target.dataset.tab); });
  $("goto-gateway").onclick = () => showTab("gateway");

  // -------------------------------------------------------------- profile tab
  function fillSelect(sel, options, value) {
    clear(sel);
    for (const [v, label] of options) sel.append(h("option", { value: v, text: label }));
    if (value !== undefined) sel.value = value;
  }
  const TYPE_OPTIONS = Object.keys(P.TYPES).map(t => [t, t]);
  fillSelect($("d-type"), TYPE_OPTIONS);

  function bind(id, get, set, parse) {
    const el = $(id);
    el.addEventListener("input", () => { set(parse ? parse(el.value) : el.value); touch(); });
    return () => { el.value = get(); };
  }
  const num = v => (v === "" ? undefined : Number(String(v).replace(",", ".")));
  const optional = (obj, key) => (v => { if (v === "" || v === undefined || Number.isNaN(v)) delete obj()[key]; else obj()[key] = v; });

  const profileBinders = [];
  function bindProfileFields() {
    const prof = () => S.profile;
    const text = (id, key) => profileBinders.push(bind(id, () => prof()[key] || "", v => { if (v === "") delete prof()[key]; else prof()[key] = v; }));
    text("p-vendor", "vendor"); text("p-model", "model"); text("p-notes", "notes");
    profileBinders.push(bind("p-name", () => prof().name || "", v => {
      prof().name = v;
      if (!S.idTouched) { prof().id = I.idFromName(v); $("p-id").value = prof().id; }
    }));
    $("p-id").addEventListener("input", () => { S.idTouched = true; S.profile.id = $("p-id").value.trim(); touch(); });
    profileBinders.push(() => { $("p-id").value = prof().id || ""; });
    profileBinders.push(bind("p-rev", () => prof().rev === undefined ? 1 : prof().rev, v => { prof().rev = v; }, v => (v === "" ? 1 : Number(v))));
    $("p-transport").addEventListener("change", () => { prof().transport = $("p-transport").value; touch(); });
    profileBinders.push(() => { $("p-transport").value = prof().transport || "tcp"; });

    const timing = (id, key) => profileBinders.push(bind(id, () => (prof().timing || {})[key] ?? P.TIMING_DEFAULTS[key], v => {
      prof().timing = prof().timing || {};
      prof().timing[key] = v;
      if (key === "max_block") $("t-merge").checked = v > 1;
    }, v => (v === "" ? P.TIMING_DEFAULTS[key] : Number(v))));
    timing("t-gap", "read_gap_ms"); timing("t-timeout", "timeout_ms"); timing("t-retries", "retries"); timing("t-block", "max_block");
    $("t-merge").addEventListener("change", () => {
      prof().timing = prof().timing || {};
      prof().timing.max_block = $("t-merge").checked ? 16 : 1;
      $("t-block").value = prof().timing.max_block;
      touch();
    });
    profileBinders.push(() => { $("t-merge").checked = ((prof().timing || {}).max_block || 1) > 1; });

    const dflt = (id, key, conv) => {
      $(id).addEventListener("change", () => { prof().defaults = prof().defaults || {}; prof().defaults[key] = conv ? conv($(id).value) : $(id).value; renderRegs(); touch(); });
      profileBinders.push(() => { $(id).value = String((prof().defaults || {})[key] ?? P.REG_DEFAULTS[key]); });
    };
    dflt("d-fc", "fc", Number); dflt("d-type", "type"); dflt("d-word", "word_order"); dflt("d-byte", "byte_order");
  }

  // -- library
  function renderLibrary() {
    const sel = $("libsel");
    clear(sel);
    sel.append(h("option", { value: "", text: "— choose a profile —" }));
    const saved = library.all();
    const g1 = h("optgroup", { label: "Saved on this device" });
    for (const id of Object.keys(saved).sort()) g1.append(h("option", { value: "s:" + id, text: `${saved[id].name || id} (${id})` }));
    const g2 = h("optgroup", { label: "Examples" });
    for (const p of shipped()) g2.append(h("option", { value: "x:" + p.id, text: `${p.name} (${p.id})` }));
    if (g1.children.length) sel.append(g1);
    sel.append(g2);
    sel.value = "";
  }
  $("libsel").addEventListener("change", () => {
    const v = $("libsel").value;
    if (!v) return;
    const id = v.slice(2);
    const p = v[0] === "s" ? library.all()[id] : shipped().find(x => x.id === id);
    if (p && confirmDiscard()) { setProfile(JSON.parse(JSON.stringify(p))); toast("Loaded " + (p.name || id)); }
    $("libsel").value = "";
  });
  $("libnew").onclick = () => { if (confirmDiscard()) { setProfile(P.newProfile()); S.idTouched = false; } };
  $("libdup").onclick = () => {
    const p = JSON.parse(JSON.stringify(S.profile));
    p.id = (p.id || "profile").slice(0, 21) + "-copy"; p.name = (p.name || "Profile").slice(0, 43) + " (copy)";
    setProfile(p); S.idTouched = true; touch();
  };
  $("libdel").onclick = () => {
    const id = S.profile.id;
    if (!library.all()[id]) { toast("That profile is not saved on this device."); return; }
    if (window.confirm(`Delete "${id}" from this device? (The gateway keeps its own copy.)`)) { library.remove(id); renderLibrary(); toast("Deleted " + id); }
  };
  $("libexport").onclick = () => {
    const name = (S.profile.id || "profile") + ".json";
    const text = JSON.stringify(P.normalize(S.profile), null, 2) + "\n";
    if (window.OsosAndroid && window.OsosAndroid.shareText) { window.OsosAndroid.shareText(name, text); return; }
    const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "application/json" })), download: name });
    document.body.append(a); a.click(); a.remove();
  };
  $("libimport").addEventListener("change", async e => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      const p = JSON.parse(await f.text());
      const errs = P.errorsOf(P.validate(P.normalize(p)));
      if (!confirmDiscard()) return;
      setProfile(p);
      toast(errs.length ? `Opened with ${errs.length} problem(s) to fix` : "Opened " + f.name, errs.length ? "bad" : "ok");
    } catch (err) { toast("That is not a profile JSON file.", "bad"); }
  });
  $("save").onclick = () => {
    const errs = P.errorsOf(P.validate(S.profile));
    if (errs.length) { toast(errs[0].msg, "bad"); return; }
    if (library.save(S.profile)) {
      S.savedJson = JSON.stringify(S.profile);
      renderLibrary();
      $("savemsg").textContent = `Saved "${S.profile.id}" on this device.`;
      toast("Saved", "ok");
    } else toast("This browser would not let the page store anything.", "bad");
  };

  // -- registers table
  function widthOf(r) {
    const t = r.type || (S.profile.defaults || {}).type || "f32";
    return P.TYPES[t] ? P.TYPES[t][0] : 1;
  }

  function regCell(i, field, kind, options) {
    const r = S.profile.registers[i];
    const setv = v => {
      if (v === undefined || v === "" || (typeof v === "number" && Number.isNaN(v))) delete r[field];
      else r[field] = v;
      touch();
    };
    if (kind === "select") {
      const sel = h("select", { "aria-label": field });
      sel.append(h("option", { value: "", text: "(default)" }));
      for (const [v, l] of options) sel.append(h("option", { value: v, text: l }));
      sel.value = r[field] === undefined ? "" : String(r[field]);
      sel.addEventListener("change", () => { setv(sel.value === "" ? undefined : (field === "fc" ? Number(sel.value) : sel.value)); renderRegs(); });
      return sel;
    }
    const inp = h("input", { type: "text", value: r[field] === undefined ? "" : String(r[field]), "aria-label": field, spellcheck: "false" });
    if (field === "scale" || field === "offset") inp.placeholder = String((S.profile.defaults || {})[field] ?? P.REG_DEFAULTS[field]);
    inp.addEventListener("input", () => {
      if (kind === "int") setv(inp.value === "" ? undefined : Number(inp.value));
      else if (kind === "number") setv(inp.value === "" ? undefined : Number(inp.value.replace(",", ".")));
      else setv(inp.value);
    });
    return inp;
  }

  function renderRegs() {
    const tbl = clear($("regtable"));
    tbl.append(h("thead", {}, h("tr", {}, ["Key", "Address", "Func", "Type", "Words", "Bytes", "Scale", "Offset", "Unit", "Label", "Dec", "", "Test"].map(t => h("th", { text: t })))));
    const body = h("tbody");
    const FC = [[3, "03"], [4, "04"]];
    const ORD_W = [["big", "ABCD"], ["little", "CDAB"]];
    const ORD_B = [["big", "normal"], ["little", "swap"]];
    S.profile.registers.forEach((r, i) => {
      const t = S.tests[i];
      body.append(h("tr", { "data-i": i },
        h("td", { class: "k" }, regCell(i, "key", "text")),
        h("td", { class: "a" }, regCell(i, "address", "int")),
        h("td", { class: "s" }, regCell(i, "fc", "select", FC)),
        h("td", { class: "s" }, regCell(i, "type", "select", TYPE_OPTIONS)),
        h("td", { class: "s" }, regCell(i, "word_order", "select", ORD_W)),
        h("td", { class: "s" }, regCell(i, "byte_order", "select", ORD_B)),
        h("td", { class: "n" }, regCell(i, "scale", "number")),
        h("td", { class: "n" }, regCell(i, "offset", "number")),
        h("td", { class: "u" }, regCell(i, "unit", "text")),
        h("td", { class: "l" }, regCell(i, "label", "text")),
        h("td", { class: "n" }, regCell(i, "decimals", "int")),
        h("td", { class: "act" },
          h("button", { title: "Duplicate", onclick: () => dupReg(i), text: "⧉" }),
          h("button", { title: "Remove", class: "danger", onclick: () => { S.profile.registers.splice(i, 1); S.tests = {}; renderRegs(); touch(); }, text: "✕" })),
        h("td", { class: "act" }, h("button", { onclick: () => testReg(i), text: "Test" })),
        h("td", { class: "res " + (t ? (t.ok ? "ok" : "bad") : ""), text: t ? t.text : "" })));
    });
    tbl.append(body);
    renderCount();
  }
  function renderCount() {
    const n = S.profile.registers.length;
    $("regcount").textContent = `${n} of ${P.MAX_REGS}`;
  }
  $("reg-add").onclick = () => {
    const regs = S.profile.registers;
    const last = regs[regs.length - 1];
    const addr = last ? last.address + widthOf(last) : 0;
    regs.push({ key: P.makeKey("Reg " + addr, new Set(regs.map(r => r.key))), address: addr });
    renderRegs(); touch();
    const rows = $("regtable").querySelectorAll("tbody tr");
    const inp = rows[rows.length - 1] && rows[rows.length - 1].querySelector("input");
    if (inp) inp.focus();
  };
  function dupReg(i) {
    const r = JSON.parse(JSON.stringify(S.profile.registers[i]));
    r.address = Math.min(65535, r.address + widthOf(r));
    r.key = P.makeKey(r.key, new Set(S.profile.registers.map(x => x.key)));
    S.profile.registers.splice(i + 1, 0, r);
    S.tests = {}; renderRegs(); touch();
  }
  $("reg-sort").onclick = () => {
    S.profile.registers.sort((a, b) => ((a.fc || S.profile.defaults.fc) - (b.fc || S.profile.defaults.fc)) || (a.address - b.address));
    S.tests = {}; renderRegs(); touch();
  };
  $("reg-shift").onclick = () => {
    if (!window.confirm("Subtract 1 from every address? Use this when the manual counts registers from 1.")) return;
    for (const r of S.profile.registers) r.address = Math.max(0, r.address - 1);
    S.tests = {}; renderRegs(); touch();
  };

  async function testReg(i) {
    const r = S.profile.registers[i];
    if (!S.mid || !S.aid) { toast("Pick a modem and analyzer above first.", "bad"); return; }
    const d = P.resolveReg(r, S.profile.defaults || {});
    S.tests[i] = { ok: true, text: "reading…" };
    renderRegs();
    const args = { analyzer: S.aid, address: r.address, fc: d.fc, type: d.type, word_order: d.word_order, byte_order: d.byte_order, scale: d.scale, offset: d.offset };
    if (r.decimals !== undefined) args.decimals = r.decimals;
    const ack = await send("profile_test", args);
    S.tests[i] = ack ? { ok: ack.ok, text: ack.detail } : { ok: false, text: "no answer from the gateway" };
    renderRegs();
  }

  // -- tile pages
  function renderViews() {
    const box = clear($("views"));
    const keys = S.profile.registers.map(r => r.key).filter(Boolean);
    S.profile.views.forEach((v, vi) => {
      const chips = h("div", { class: "chips" }, keys.map(k => h("span", {
        class: "chip" + (v.keys.includes(k) ? " on" : ""), text: k, role: "button", tabindex: "0",
        onclick: ev => {
          const at = v.keys.indexOf(k);
          if (at >= 0) v.keys.splice(at, 1); else if (v.keys.length < P.MAX_VIEW_KEYS) v.keys.push(k);
          ev.target.classList.toggle("on", v.keys.includes(k)); touch();
        },
      })));
      box.append(h("div", { class: "viewbox" },
        h("div", { class: "row" },
          h("input", { value: v.id, placeholder: "id", "aria-label": "page id", oninput: ev => { v.id = ev.target.value.trim(); touch(); } }),
          h("input", { value: v.label || "", placeholder: "label", "aria-label": "page label", oninput: ev => { v.label = ev.target.value; touch(); } }),
          h("button", { class: "danger", text: "✕", title: "Remove page", onclick: () => { S.profile.views.splice(vi, 1); renderViews(); touch(); } })),
        chips));
    });
    if (!S.profile.views.length) box.append(h("p", { class: "muted", text: "No pages: the app will show every register on one page." }));
  }
  $("view-add").onclick = () => {
    if (S.profile.views.length >= P.MAX_VIEWS) { toast("At most " + P.MAX_VIEWS + " pages."); return; }
    S.profile.views.push({ id: "page" + (S.profile.views.length + 1), label: "Page " + (S.profile.views.length + 1), keys: [] });
    renderViews(); touch();
  };
  $("view-auto").onclick = () => {
    const keys = S.profile.registers.map(r => r.key).filter(Boolean);
    S.profile.views = [];
    for (let i = 0; i < keys.length && S.profile.views.length < P.MAX_VIEWS; i += 12) {
      const n = S.profile.views.length + 1;
      S.profile.views.push(keys.length <= 12 ? { id: "all", label: "all", keys: keys.slice(i, i + 12) } : { id: "p" + n, label: "page " + n, keys: keys.slice(i, i + 12) });
    }
    renderViews(); touch();
  };

  // -- validation
  function renderIssues() {
    const box = clear($("issues"));
    const iss = P.validate(S.profile);
    if (!iss.length) {
      const { timing, regs } = P.resolve(S.profile);
      const blocks = P.planBlocks(regs, timing.max_block).length;
      box.append(h("div", { class: "issue ok", text: `No problems. ${regs.length} register(s) are read in ${blocks} request(s) per sweep.` }));
    }
    for (const i of iss) {
      box.append(h("div", {
        class: "issue " + i.level, title: i.code,
        text: (i.path ? i.path + ": " : "") + i.msg,
        onclick: () => {
          const m = /^registers\[(\d+)\]/.exec(i.path);
          if (!m) return;
          const row = $("regtable").querySelector(`tr[data-i="${m[1]}"]`);
          if (row) { row.scrollIntoView({ block: "center" }); const inp = row.querySelector("input"); if (inp) inp.focus(); }
        },
      }));
    }
    // flag rows with errors
    const bad = new Set(iss.filter(i => i.level === "error").map(i => (/^registers\[(\d+)\]/.exec(i.path) || [])[1]));
    for (const tr of $("regtable").querySelectorAll("tbody tr")) tr.classList.toggle("bad", bad.has(tr.dataset.i));
  }

  function renderProfile() {
    for (const f of profileBinders) f();
    renderLibrary();
    renderRegs();
    renderViews();
    renderIssues();
    renderSendInfo();
  }

  // -------------------------------------------------------------- import tab
  let pdfLoading = null;
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = h("script", { src });
      s.onload = resolve;
      s.onerror = () => reject(new Error("Could not load " + src));
      document.head.append(s);
    });
  }
  async function ensurePdfJs() {
    if (window.pdfjsLib) return window.pdfjsLib;
    if (!pdfLoading) {
      pdfLoading = loadScript("vendor/pdf.min.js").then(() => {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdf.worker.min.js";
        return window.pdfjsLib;
      });
    }
    return pdfLoading;
  }

  async function handleFile(file) {
    const st = $("docstatus");
    st.textContent = `Reading ${file.name}…`;
    $("import-review").hidden = true;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const isPdf = /\.pdf$/i.test(file.name);
      S.doc = await I.readDocument({ name: file.name, bytes }, { pdfjsLib: isPdf ? await ensurePdfJs() : null });
      S.docName = file.name;
      $("io-name").value = file.name.replace(/\.[A-Za-z0-9]+$/, "").slice(0, 48);
      $("io-id").value = I.idFromName(file.name);
      analyzeDoc();
    } catch (e) {
      S.doc = null;
      st.textContent = "";
      toast(e.message || String(e), "bad");
    }
  }
  $("docfile").addEventListener("change", e => { const f = e.target.files[0]; e.target.value = ""; if (f) handleFile(f); });
  const drop = $("drop");
  for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); });
  for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); });
  drop.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) handleFile(f); });

  function ioOpts() {
    const o = {};
    if ($("io-base").value === "1") o.base = 1;
    o.default32 = $("io-32").value;
    if ($("io-fc").value) o.fc = Number($("io-fc").value);
    return o;
  }
  function analyzeDoc() {
    if (!S.doc) return;
    S.draft = I.analyze(S.doc, ioOpts());
    const sel = S.draft.rows.filter(r => r.include).length;
    $("docstatus").textContent = `${S.docName}: ${S.draft.rows.length} register(s) found` + (S.draft.rows.length ? "." : ". Nothing recognisable.");
    $("import-review").hidden = !S.draft.rows.length && !S.draft.warnings.length;
    renderDraft();
  }
  for (const id of ["io-base", "io-32", "io-fc"]) $(id).addEventListener("change", analyzeDoc);

  function renderDraft() {
    const d = S.draft;
    const warn = clear($("docwarnings"));
    for (const w of d.warnings) warn.append(h("div", { class: "issue warn", text: w }));
    for (const n of d.hints.notes) warn.append(h("div", { class: "muted", text: "Note: " + n }));
    const tbl = clear($("drafttable"));
    tbl.append(h("thead", {}, h("tr", {}, ["", "Key", "Label", "Address", "Func", "Type", "Scale", "Unit", "Sure?", "Notes"].map(t => h("th", { text: t })))));
    const body = h("tbody");
    d.rows.forEach(r => {
      const edit = (field, conv) => h("input", { value: r[field] === undefined ? "" : String(r[field]), "aria-label": field, oninput: ev => { const v = ev.target.value; r[field] = conv ? conv(v) : v; updateCount(); } });
      body.append(h("tr", {},
        h("td", {}, h("input", { type: "checkbox", checked: r.include, "aria-label": "include", onchange: ev => { r.include = ev.target.checked; updateCount(); } })),
        h("td", { class: "k" }, edit("key")),
        h("td", { class: "l" }, edit("label")),
        h("td", { class: "a" }, edit("address", Number)),
        h("td", { class: "s" }, (() => { const s = h("select", {}, h("option", { value: "3", text: "03" }), h("option", { value: "4", text: "04" })); s.value = String(r.fc); s.onchange = () => { r.fc = Number(s.value); }; return s; })()),
        h("td", { class: "s" }, (() => { const s = h("select", {}, TYPE_OPTIONS.map(([v, l]) => h("option", { value: v, text: l }))); s.value = r.type; s.onchange = () => { r.type = s.value; }; return s; })()),
        h("td", { class: "n" }, edit("scale", v => Number(String(v).replace(",", ".")))),
        h("td", { class: "u" }, edit("unit")),
        h("td", {}, h("span", { class: "badge " + r.confidence, text: r.confidence })),
        h("td", { class: "notes", text: r.notes.join(" · ") })));
    });
    tbl.append(body);
    updateCount();
  }
  function updateCount() {
    const n = S.draft ? S.draft.rows.filter(r => r.include).length : 0;
    $("io-count").textContent = `${n} selected` + (n > P.MAX_REGS ? ` (a profile holds at most ${P.MAX_REGS})` : "");
  }
  function selectRows(fn) { for (const r of S.draft.rows) r.include = fn(r); renderDraft(); }
  $("io-all").onclick = () => selectRows(() => true);
  $("io-none").onclick = () => selectRows(() => false);
  $("io-sure").onclick = () => selectRows(r => r.confidence === "high");

  function draftMeta() {
    return {
      id: $("io-id").value.trim(), name: $("io-name").value.trim(), hints: S.draft.hints,
      merge: $("io-merge").checked, wordOrder: $("io-word").value || undefined,
    };
  }
  $("io-use").onclick = () => {
    const rows = S.draft.rows.filter(r => r.include);
    if (!rows.length) { toast("Select at least one register.", "bad"); return; }
    if (rows.length > P.MAX_REGS) { toast(`Select at most ${P.MAX_REGS} registers.`, "bad"); return; }
    if (!confirmDiscard()) return;
    setProfile(I.toProfile(S.draft.rows, draftMeta()));
    S.idTouched = true;
    showTab("profile");
    toast(`Created a profile with ${rows.length} register(s). Check it, then Test a few.`, "ok");
  };
  $("io-append").onclick = () => {
    const rows = S.draft.rows.filter(r => r.include);
    const regs = S.profile.registers;
    if (regs.length + rows.length > P.MAX_REGS) { toast(`That would be more than ${P.MAX_REGS} registers.`, "bad"); return; }
    const taken = new Set(regs.map(r => r.key));
    const d = S.profile.defaults || P.REG_DEFAULTS;
    for (const r of rows) {
      const o = { key: P.makeKey(r.key, taken), address: r.address };
      taken.add(o.key);
      if (r.fc !== d.fc) o.fc = r.fc;
      if (r.type !== d.type) o.type = r.type;
      if (r.scale !== 1) o.scale = r.scale;
      if (r.decimals !== undefined) o.decimals = r.decimals;
      if (r.unit) o.unit = r.unit.slice(0, 8);
      if (r.label) o.label = r.label.slice(0, 40);
      regs.push(o);
    }
    renderRegs(); renderIssues(); showTab("profile");
    toast(`Added ${rows.length} register(s).`, "ok");
  };

  // -------------------------------------------------------------- fleet / target
  function modemList() { return Object.keys(S.fleet.modems).sort(); }
  function analyzerList() { const m = S.fleet.modems[S.mid]; return m ? Object.keys(m.analyzers).sort() : []; }

  function renderTarget() {
    const mids = modemList();
    if (!S.mid && mids.length) S.mid = mids[0];
    const ms = $("modemsel");
    const want = JSON.stringify(mids);
    if (ms.dataset.sig !== want) {
      fillSelect(ms, mids.length ? mids.map(m => [m, m]) : [["", "(none seen yet)"]]);
      ms.dataset.sig = want;
    }
    ms.value = S.mid || "";
    const aids = analyzerList();
    if (!aids.includes(S.aid)) S.aid = aids[0] || null;
    const as = $("analyzersel");
    const wantA = S.mid + JSON.stringify(aids);
    if (as.dataset.sig !== wantA) {
      fillSelect(as, aids.length ? aids.map(a => [a, a]) : [["", "(none)"]]);
      as.dataset.sig = wantA;
    }
    as.value = S.aid || "";
    const m = S.fleet.modems[S.mid];
    const info = [];
    if (m && m.status) info.push(`${m.status.state}${m.status.fw ? " · fw " + m.status.fw : ""}${m.status.ip ? " · " + m.status.ip : ""}`);
    if (m && m.profiles && S.aid) info.push(`${S.aid} reads as ${m.profiles.assign[S.aid] || "?"}`);
    $("targetinfo").textContent = info.join(" — ") || "Waiting for a gateway…";
  }
  $("modemsel").addEventListener("change", () => { S.mid = $("modemsel").value || null; S.aid = null; renderAll(); });
  $("analyzersel").addEventListener("change", () => { S.aid = $("analyzersel").value || null; renderAll(); });

  function updatePill() {
    const pill = $("connpill");
    pill.className = "pill " + (S.connected ? "online" : "offline");
    pill.textContent = S.connected ? "broker connected" : "no broker";
  }

  async function send(action, args) {
    if (!S.mid) return { ok: false, detail: "no modem selected" };
    if (!S.connected) return { ok: false, detail: "not connected to the broker" };
    return transport.send(S.mid, action, args);
  }

  // ------------------------------------------------------------- gateway tab
  function renderSendInfo() {
    const box = clear($("sendinfo"));
    const p = S.profile;
    if (!p) return;
    const errs = P.errorsOf(P.validate(p));
    box.append(h("div", { text: `${p.name || "(no name)"} · id ${p.id || "?"} · rev ${p.rev} · ${p.registers.length} register(s)` }));
    if (errs.length) box.append(h("div", { class: "issue error", text: `${errs.length} problem(s) to fix first: ${errs[0].msg}` }));
    $("send").disabled = !!errs.length || S.sending;
  }

  function renderGateway() {
    const m = S.fleet.modems[S.mid];
    const info = clear($("gwinfo"));
    const list = clear($("gwprofiles"));
    if (!m) { info.textContent = "No gateway seen yet."; return; }
    if (!m.profiles) {
      info.textContent = "This gateway has not announced any profiles. Its firmware may be older than profile support.";
      return;
    }
    const cap = m.profiles.cap || {};
    info.textContent = `Holds up to ${cap.profiles} stored profiles of ${cap.regs} registers. ${cap.free !== undefined ? Math.round(cap.free / 1024) + " KB free." : ""}`;
    const use = {};
    for (const [a, pid] of Object.entries(m.profiles.assign || {})) (use[pid] = use[pid] || []).push(a);
    for (const it of m.profiles.profiles) {
      const users = use[it.id] || [];
      list.append(h("div", { class: "gwprofile" },
        h("div", { class: "grow" }, `${it.name || it.id}`, h("small", { text: `${it.id} · rev ${it.rev} · ${it.n} registers${it.builtin ? " · built in" : ""}${users.length ? " · used by " + users.join(", ") : ""}` })),
        S.aid && !users.includes(S.aid) ? h("button", { text: "Use for " + S.aid, onclick: () => assign(it.id) }) : null,
        !it.builtin && !users.length ? h("button", { class: "danger", text: "Delete", onclick: () => removeStored(it.id) }) : null));
    }
    renderSendInfo();
  }
  async function assign(pid) {
    const ack = await send("profile_assign", { analyzer: S.aid, profile: pid });
    toast(ack ? (ack.ok ? ack.detail : "Refused: " + ack.detail) : "No answer from the gateway", ack && ack.ok ? "ok" : "bad");
  }
  async function removeStored(pid) {
    if (!window.confirm(`Delete "${pid}" from the gateway?`)) return;
    const ack = await send("profile_delete", { id: pid });
    toast(ack ? (ack.ok ? ack.detail : "Refused: " + ack.detail) : "No answer from the gateway", ack && ack.ok ? "ok" : "bad");
  }
  $("gw-refresh").onclick = async () => { const ack = await send("profile_list", {}); if (!ack || !ack.ok) toast("No answer from the gateway", "bad"); };

  $("gw-pull").onclick = () => {
    const p = F.profileOf(S.fleet, S.mid, S.aid);
    if (!p) { toast("The gateway has not published a profile for this analyzer.", "bad"); return; }
    if (!confirmDiscard()) return;
    setProfile(JSON.parse(JSON.stringify(p)));
    showTab("profile");
    toast("Loaded the gateway's profile into the editor.", "ok");
  };

  function logLine(text, cls) {
    const log = $("sendlog");
    log.append(h("div", { class: cls || "", text }));
    log.scrollTop = log.scrollHeight;
  }
  $("send").onclick = async () => {
    if (S.sending) return;
    if (!S.mid) { toast("No gateway selected.", "bad"); return; }
    S.sending = true;
    S.abort = new AbortController();
    clear($("sendlog"));
    const bar = $("sendprogress");
    bar.hidden = false; bar.value = 0; bar.max = 1;
    $("send").disabled = true; $("send-cancel").hidden = false;
    const assignTo = $("send-assign").checked && S.aid ? { analyzer: S.aid } : null;
    try {
      await U.upload(P.normalize(S.profile), (a, x) => send(a, x), {
        assign: assignTo, signal: S.abort.signal,
        verifyStored: async p => {
          await send("profile_list", {});
          await new Promise(r => setTimeout(r, 1200));
          const m = S.fleet.modems[S.mid];
          return !!(m && m.profiles && m.profiles.profiles.some(x => x.id === p.id && x.rev === p.rev));
        },
        onProgress: (i, n, action, detail) => { bar.max = n; bar.value = i; logLine(`${i}/${n} ${action}: ${detail}`); },
      });
      toast(`Sent "${S.profile.id}" to ${S.mid}.` + (assignTo ? ` ${assignTo.analyzer} now reads with it.` : ""), "ok");
      logLine("Done.");
      S.savedJson = S.savedJson; // sending does not save locally; leave the dirty state as is
    } catch (e) {
      logLine(`Stopped at ${e.action || "?"}: ${e.message}`, "err");
      toast("Not sent: " + e.message, "bad");
    } finally {
      S.sending = false; S.abort = null;
      $("send-cancel").hidden = true; bar.hidden = true;
      renderSendInfo();
    }
  };
  $("send-cancel").onclick = () => { if (S.abort) S.abort.abort(); };

  // ----------------------------------------------------------------- live tab
  function renderLive() {
    const a = (S.fleet.modems[S.mid] || { analyzers: {} }).analyzers[S.aid];
    const meta = $("livemeta"), tabs = clear($("liveviews")), tiles = clear($("livetiles"));
    if (!a || !a.telemetry) { meta.textContent = "No telemetry yet for this analyzer."; return; }
    const t = a.telemetry;
    const prof = a.profile;
    meta.textContent = `seq ${t.seq} · ${t.ts || ""} · meter ${t.meter_ok ? "ok" : "FAULT"} · profile ${t.profile || "?"}${t.profile_rev !== undefined ? " rev " + t.profile_rev : ""}` +
      (prof && t.profile && prof.id !== t.profile ? " (the profile shown here is out of date)" : "");
    const views = prof ? P.viewsOf(prof) : [{ id: "all", label: "all", keys: Object.keys(t.values || {}) }];
    if (!views.some(v => v.id === S.liveView)) S.liveView = views[0].id;
    for (const v of views) tabs.append(h("button", { class: v.id === S.liveView ? "active" : "", text: v.label || v.id, onclick: () => { S.liveView = v.id; renderLive(); } }));
    const view = views.find(v => v.id === S.liveView);
    const regs = {};
    if (prof) for (const r of prof.registers) regs[r.key] = r;
    for (const key of view.keys) {
      const r = regs[key] || {};
      const val = t.values ? t.values[key] : undefined;
      const missing = val === null || val === undefined;
      const dec = r.decimals !== undefined ? r.decimals : 2;
      tiles.append(h("div", { class: "tile" },
        h("div", { class: "k", text: r.label || key }),
        h("div", { class: "v" + (missing ? " null" : "") }, missing ? "—" : Number(val).toFixed(Math.min(dec, 3)), r.unit ? h("small", { text: " " + r.unit }) : null)));
    }
  }

  // ------------------------------------------------------------------- wiring
  let transport;
  const renderAll = () => {
    renderTarget();
    if (S.tab === "gateway") renderGateway();
    if (S.tab === "live") renderLive();
  };
  const renderSoon = debounce(renderAll, 120);

  function start() {
    bindProfileFields();
    setProfile(P.newProfile());
    S.idTouched = false;
    updatePill();
    try {
      transport = window.OsosTransport.create(window);
    } catch (e) {
      $("connpill").textContent = "no transport";
      toast(e.message, "bad");
      return;
    }
    transport.onState(ok => { S.connected = ok; updatePill(); });
    transport.onMessage((topic, text) => {
      const r = F.apply(S.fleet, topic, text);
      if (r.changed) renderSoon();
    });
    transport.connect();
    renderTarget();
    // "back to the HMI" keeps the modem choice
    if (S.mid) $("backlink").href = "../index.html?modem=" + encodeURIComponent(S.mid);
  }

  window.OsosMapApp = { state: S, showTab, setProfile, analyzeDoc };   // handles for tests
  start();
})();
