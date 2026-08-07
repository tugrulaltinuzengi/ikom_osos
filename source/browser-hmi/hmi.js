// HMI glue: MQTT wiring, digit->command dispatch, confirm gate,
// user-defined hand-drawn commands (embedding match), telemetry views.
"use strict";

/* ---------------- config ---------------- */
const qs = new URLSearchParams(location.search);
const CFG0 = window.OSOS_CONFIG || {};
const CFG = {
  wssUrl:  qs.get("wss")  || CFG0.wssUrl  || "wss://broker.emqx.io:8084/mqtt",
  username: qs.get("user") ?? CFG0.username ?? "",
  password: qs.get("pass") ?? CFG0.password ?? "",
  gwId:    qs.get("gw")   || CFG0.gwId    || "dkm440-gw1",
  confMin: parseFloat(qs.get("conf") || CFG0.confMin || 0.90),
  simMin:  parseFloat(qs.get("sim")  || CFG0.simMin  || 0.93),
};
const T = {
  telemetry: `osos/${CFG.gwId}/telemetry`,
  status:    `osos/${CFG.gwId}/status`,
  event:     `osos/${CFG.gwId}/event`,
  cmd:       `osos/${CFG.gwId}/cmd`,
  ack:       `osos/${CFG.gwId}/ack`,
};

/* ---------------- dom ---------------- */
const $ = id => document.getElementById(id);
const pill = $("gwpill"), predbox = $("predbox"), banner = $("banner");
const confirmbar = $("confirmbar"), confirmtext = $("confirmtext");
const tilesEl = $("tiles"), metaEl = $("meta"), viewtabsEl = $("viewtabs");
const eventlog = $("eventlog");

/* ---------------- actions a custom symbol can be bound to ------------- */
const ACTIONS = [
  { key: "read_now",   label: "read now (fresh telemetry)", scope: "gateway", action: "read_now",     args: {} },
  { key: "ping",       label: "ping gateway",               scope: "gateway", action: "ping",         args: {} },
  { key: "int2",       label: "fast reporting (2 s)",       scope: "gateway", action: "set_interval", args: { seconds: 2 } },
  { key: "int10",      label: "normal reporting (10 s)",    scope: "gateway", action: "set_interval", args: { seconds: 10 } },
  { key: "viewL1",     label: "read/show register L1",      scope: "local",   action: "view",         args: { page: "L1" } },
  { key: "viewL2",     label: "read/show register L2",      scope: "local",   action: "view",         args: { page: "L2" } },
  { key: "viewL3",     label: "read/show register L3",      scope: "local",   action: "view",         args: { page: "L3" } },
  { key: "viewOvw",    label: "show overview",              scope: "local",   action: "view",         args: { page: "overview" } },
  { key: "viewPow",    label: "show power factors",         scope: "local",   action: "view",         args: { page: "power" } },
];

/* ---------------- telemetry views ---------------- */
const VIEWS = {
  overview: ["MainBus_Voltage_L1", "MainBus_Voltage_L2", "MainBus_Voltage_L3",
             "MainBus_Current_L1", "MainBus_Current_L2", "MainBus_Current_L3",
             "MainBus_Freq_L1", "Supply_Voltage",
             "MainBus_Voltage_N", "MainBus_Current_N"],
  L1: ["MainBus_Voltage_L1", "MainBus_Current_L1", "MainBus_Freq_L1",
       "MainBus_PF_L1", "MainBus_CosPhi_L1", "MainBus_TanPhi_L1"],
  L2: ["MainBus_Voltage_L2", "MainBus_Current_L2", "MainBus_Freq_L2",
       "MainBus_PF_L2", "MainBus_CosPhi_L2", "MainBus_TanPhi_L2"],
  L3: ["MainBus_Voltage_L3", "MainBus_Current_L3", "MainBus_Freq_L3",
       "MainBus_PF_L3", "MainBus_CosPhi_L3", "MainBus_TanPhi_L3"],
  power: ["MainBus_PF_L1", "MainBus_PF_L2", "MainBus_PF_L3",
          "MainBus_CosPhi_L1", "MainBus_CosPhi_L2", "MainBus_CosPhi_L3",
          "MainBus_TanPhi_Tot", "MainBus_TanPhi_L1", "MainBus_TanPhi_L2", "MainBus_TanPhi_L3"],
};
function unitOf(key) {
  if (key.includes("Voltage")) return "V";
  if (key.includes("Current")) return "A";
  if (key.includes("Freq")) return "Hz";
  return "";
}
function shortName(key) {
  return key.replace("MainBus_", "").replace(/_/g, " ");
}

let activeView = "overview";
let lastTelemetry = null;

function renderTabs() {
  viewtabsEl.innerHTML = "";
  for (const v of Object.keys(VIEWS)) {
    const b = document.createElement("button");
    b.textContent = v;
    if (v === activeView) b.classList.add("active");
    b.onclick = () => setView(v);
    viewtabsEl.appendChild(b);
  }
}
function setView(v) {
  if (!VIEWS[v]) return;
  activeView = v;
  renderTabs();
  renderTiles();
}
function renderTiles() {
  tilesEl.innerHTML = "";
  for (const key of VIEWS[activeView]) {
    const val = lastTelemetry ? lastTelemetry.values?.[key] : undefined;
    const tile = document.createElement("div");
    tile.className = "tile";
    const isNull = val === null || val === undefined;
    tile.innerHTML = `<div class="k">${shortName(key)}</div>
      <div class="v${isNull ? " null" : ""}">${isNull ? "—" : Number(val).toFixed(2)}
      <small>${unitOf(key)}</small></div>`;
    tilesEl.appendChild(tile);
  }
  if (lastTelemetry) {
    metaEl.textContent = `seq ${lastTelemetry.seq} · ${lastTelemetry.ts} · meter ${lastTelemetry.meter_ok ? "ok" : "FAULT"}`;
  }
}

/* ---------------- banner / log ---------------- */
let bannerTimer = null;
function showBanner(kind, text, ms = 5000) {
  banner.className = kind;
  banner.textContent = text;
  clearTimeout(bannerTimer);
  if (ms) bannerTimer = setTimeout(() => { banner.className = ""; }, ms);
}
function setPred(big, pct, sub) {
  predbox.textContent = "";
  const b = document.createElement("b");
  b.textContent = big;
  predbox.appendChild(b);
  predbox.appendChild(document.createTextNode(" " + pct));
  predbox.appendChild(document.createElement("br"));
  const s = document.createElement("span");
  s.className = "muted";
  s.textContent = sub;
  predbox.appendChild(s);
}
function logEvent(text) {
  const line = document.createElement("div");
  line.textContent = `${new Date().toLocaleTimeString()} ${text}`;
  eventlog.prepend(line);
  while (eventlog.childNodes.length > 50) eventlog.removeChild(eventlog.lastChild);
}

/* ---------------- mqtt ---------------- */
let client = null, gwOnline = false, brokerUp = false;
function updatePill() {
  if (!brokerUp) { pill.className = "pill offline"; pill.textContent = "no broker"; }
  else if (gwOnline) { pill.className = "pill online"; pill.textContent = "gateway online"; }
  else { pill.className = "pill offline"; pill.textContent = "gateway offline"; }
}
function connectMqtt() {
  client = mqtt.connect(CFG.wssUrl, {
    username: CFG.username || undefined,
    password: CFG.password || undefined,
    clientId: "phone-" + Math.random().toString(16).slice(2, 10),
    keepalive: 30,
    clean: true,
    reconnectPeriod: 3000,
  });
  client.on("connect", () => {
    brokerUp = true; updatePill();
    client.subscribe([T.telemetry, T.status, T.event, T.ack], { qos: 1 });
    logEvent("broker connected");
  });
  client.on("close", () => { brokerUp = false; updatePill(); });
  client.on("error", e => logEvent("mqtt error: " + e.message));
  client.on("message", (topic, payload) => {
    let msg;
    try { msg = JSON.parse(payload.toString()); } catch { return; }
    if (topic === T.telemetry) { lastTelemetry = msg; renderTiles(); }
    else if (topic === T.status) { gwOnline = msg.state === "online"; updatePill(); logEvent("gateway " + msg.state); }
    else if (topic === T.event) { logEvent("event: " + (msg.type || payload)); }
    else if (topic === T.ack) { handleAck(msg); }
  });
}

/* ---------------- command dispatch ---------------- */
const pendingAcks = new Map(); // id -> timeout handle
function publishCmd(action, args) {
  const id = "c-" + Date.now().toString(36);
  client.publish(T.cmd, JSON.stringify({ id, action, args }), { qos: 1 });
  showBanner("info", `sent ${action}… waiting for gateway`, 0);
  pendingAcks.set(id, setTimeout(() => {
    pendingAcks.delete(id);
    showBanner("bad", `${action}: gateway ack timeout (10 s)`);
  }, 10000));
}
function handleAck(msg) {
  const t = pendingAcks.get(msg.id);
  if (t) { clearTimeout(t); pendingAcks.delete(msg.id); }
  showBanner(msg.ok ? "ok" : "bad", `gateway: ${msg.ok ? "OK" : "refused"} — ${msg.detail || msg.action || ""}`);
  logEvent(`ack ${msg.id}: ok=${msg.ok} ${msg.detail || ""}`);
}
let armed = null; // action awaiting the confirm tap
function armConfirm(name, act) {
  armed = act;
  confirmtext.textContent = `Send "${name}" (${act.action}${act.args?.seconds ? " " + act.args.seconds + "s" : ""})?`;
  confirmbar.style.display = "flex";
}
function disarm() { armed = null; confirmbar.style.display = "none"; }
$("yesbtn").onclick = () => { if (armed) publishCmd(armed.action, armed.args); disarm(); Pad.clear(); };
$("nobtn").onclick = () => { disarm(); Pad.clear(); showBanner("info", "cancelled"); };

function runAction(name, act) {
  if (act.scope === "local") {
    setView(act.args.page);
    showBanner("ok", `${name} → view ${act.args.page}`);
    setTimeout(() => Pad.clear(), 350);
  } else if (act.scope === "gateway") {
    armConfirm(name, act);
  } else {
    showBanner("bad", `"${name}" is unassigned`);
  }
}

/* ---------------- custom commands ---------------- */
const LS_KEY = "osos_custom_cmds_v1";
let customCmds = []; // {name, actionKey, samples: [[784]...], embeds: [Float64Array...]}
function loadCustom() {
  try { customCmds = JSON.parse(localStorage.getItem(LS_KEY)) || []; } catch { customCmds = []; }
  for (const c of customCmds) {
    c.embeds = c.samples.map(s => NN.embed(s.map(v => v / 255)));
  }
  $("managebtn").textContent = `My commands (${customCmds.length})`;
}
function saveCustom() {
  localStorage.setItem(LS_KEY, JSON.stringify(customCmds.map(c =>
    ({ name: c.name, actionKey: c.actionKey, samples: c.samples }))));
  $("managebtn").textContent = `My commands (${customCmds.length})`;
}
function matchCustom(x) {
  if (!customCmds.length) return null;
  const e = NN.embed(x);
  let best = null;
  for (const c of customCmds) {
    for (const emb of c.embeds) {
      const sim = NN.cosine(e, emb);
      if (!best || sim > best.sim) best = { cmd: c, sim };
    }
  }
  return best;
}

/* ---- add-command flow ---- */
let addMode = false, newSamples = [];
const SAMPLES_TARGET = 10, SAMPLES_MIN = 5;
$("addcmdbtn").onclick = () => {
  addMode = true; newSamples = [];
  $("addpanel").style.display = "block";
  $("managepanel").style.display = "none";
  const sel = $("cmdaction");
  if (!sel.options.length) {
    for (const a of ACTIONS) {
      const o = document.createElement("option");
      o.value = a.key; o.textContent = a.label;
      sel.appendChild(o);
    }
  }
  updateSampleProg();
  Pad.clear();
  showBanner("info", "Add-command mode: draw your symbol on the pad", 4000);
};
function updateSampleProg() {
  $("sampleprog").textContent = `samples: ${newSamples.length} / ${SAMPLES_TARGET}`;
  $("savecmdbtn").disabled = newSamples.length < SAMPLES_MIN;
  $("undosamplebtn").disabled = newSamples.length === 0;
}
$("undosamplebtn").onclick = () => { newSamples.pop(); updateSampleProg(); };
$("canceladdbtn").onclick = () => { addMode = false; $("addpanel").style.display = "none"; Pad.clear(); };
$("savecmdbtn").onclick = () => {
  const name = $("cmdname").value.trim() || "custom";
  const actionKey = $("cmdaction").value;
  const c = { name, actionKey, samples: newSamples.slice() };
  c.embeds = c.samples.map(s => NN.embed(s.map(v => v / 255)));
  customCmds.push(c);
  saveCustom();
  addMode = false;
  $("addpanel").style.display = "none";
  $("cmdname").value = "";
  Pad.clear();
  showBanner("ok", `saved "${name}" (${c.samples.length} samples)`);
};

/* ---- manage panel ---- */
$("managebtn").onclick = () => {
  $("managepanel").style.display = "block";
  $("addpanel").style.display = "none";
  renderCmdList();
};
$("closemanagebtn").onclick = () => { $("managepanel").style.display = "none"; };
function renderCmdList() {
  const list = $("cmdlist");
  list.innerHTML = customCmds.length ? "" : "none yet";
  customCmds.forEach((c, i) => {
    const a = ACTIONS.find(a => a.key === c.actionKey);
    const row = document.createElement("div");
    row.className = "cmditem";
    const span = document.createElement("span");
    span.textContent = c.name + " ";
    const small = document.createElement("small");
    small.textContent = `→ ${a ? a.label : c.actionKey} · ${c.samples.length} samples`;
    span.appendChild(small);
    row.appendChild(span);
    const del = document.createElement("button");
    del.className = "danger";
    del.textContent = "delete";
    del.onclick = () => { customCmds.splice(i, 1); saveCustom(); renderCmdList(); };
    row.appendChild(del);
    list.appendChild(row);
  });
}
// CSV export: label,p0..p783 (the format neural_net_c/src/data_mnist.cpp reads).
// Custom symbols get labels 10,11,... — retraining on the PC then needs a wider
// output layer (Network({784,128,10+N})). See README "custom symbols, phase 2".
$("exportcsvbtn").onclick = () => {
  let lines = [];
  customCmds.forEach((c, i) => {
    for (const s of c.samples) lines.push((10 + i) + "," + s.join(","));
  });
  if (!lines.length) { showBanner("bad", "no samples to export"); return; }
  const blob = new Blob([lines.join("\n") + "\n"], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "custom_symbols.csv";
  a.click();
  URL.revokeObjectURL(a.href);
};

/* ---------------- recognition routing ---------------- */
let digitMap = {}; // from commands.json
function describeDigit(d) {
  const m = digitMap[d];
  return m ? m.label : "?";
}
Pad.setOnDone(gridU8 => {
  const grid = Array.from(gridU8);
  if (addMode) {
    newSamples.push(grid);
    updateSampleProg();
    Pad.clear();
    return;
  }
  const x = grid.map(v => v / 255);
  const custom = matchCustom(x);
  const digit = NN.forward(x);

  if (custom && custom.sim >= CFG.simMin) {
    const act = ACTIONS.find(a => a.key === custom.cmd.actionKey);
    setPred(custom.cmd.name, `${(custom.sim * 100).toFixed(1)}% match`,
            `custom symbol → ${act ? act.label : "?"}`);
    if (act) runAction(custom.cmd.name, act);
    return;
  }
  const m = digitMap[digit.pred];
  setPred(String(digit.pred), `${(digit.conf * 100).toFixed(1)}%`,
          (m ? m.label : "unmapped") + (custom ? ` · best custom ${(custom.sim * 100).toFixed(0)}%` : ""));
  if (digit.conf < CFG.confMin) {
    showBanner("bad", `not sure (${(digit.conf * 100).toFixed(0)}% < ${(CFG.confMin * 100).toFixed(0)}%) — try again`);
    setTimeout(() => Pad.clear(), 600);
    return;
  }
  if (!m || m.scope === "none") {
    showBanner("bad", `digit ${digit.pred} is unassigned`);
    setTimeout(() => Pad.clear(), 600);
    return;
  }
  runAction(`digit ${digit.pred}`, m);
});

$("clearbtn").onclick = () => { Pad.clear(); disarm(); };

/* ---------------- boot ---------------- */
(async () => {
  renderTabs();
  renderTiles();
  try {
    const arch = await NN.load("weights.json");
    logEvent(`neural net loaded (${arch})`);
  } catch (e) {
    showBanner("bad", "weights.json missing — recognition disabled", 0);
  }
  try {
    const cj = await (await fetch("commands.json")).json();
    for (const [d, m] of Object.entries(cj.digits)) digitMap[d] = m;
    $("cheat").textContent = Object.entries(digitMap)
      .filter(([, m]) => m.scope !== "none")
      .map(([d, m]) => `${d}=${m.label.split(" ")[0]}`).join(" ");
  } catch { logEvent("commands.json missing"); }
  loadCustom();
  connectMqtt();
})();
