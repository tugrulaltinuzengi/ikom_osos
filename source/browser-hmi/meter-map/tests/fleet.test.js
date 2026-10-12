"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const T = require("../topics.js");
const F = require("../fleet.js");
const P = require("../profile.js");
const U = require("../uploader.js");
const Tr = require("../transport.js");
const MockGateway = require("./mockgateway.js");

const PROFILES = path.join(__dirname, "..", "..", "..", "meter-profiles");
const load = f => JSON.parse(fs.readFileSync(path.join(PROFILES, f), "utf8"));

test("topic grammar", () => {
  assert.equal(T.modemTopic("gw-01", "profiles"), "osos/m/gw-01/profiles");
  assert.equal(T.analyzerTopic("gw-01", "an-01", "profile"), "osos/m/gw-01/a/an-01/profile");
  assert.deepEqual(T.parse("osos/m/gw-01/a/an-01/profile"), { kind: "analyzer", mid: "gw-01", aid: "an-01", leaf: "profile" });
  assert.deepEqual(T.parse("osos/m/gw-01/profiles"), { kind: "modem", mid: "gw-01", aid: null, leaf: "profiles" });
  assert.equal(T.parse("osos/m/telemetry").kind, "unknown");            // reserved segment is not a legacy gateway
  assert.equal(T.parse("osos/dkm440-gw1/telemetry").kind, "legacy");
  assert.equal(T.parse("other/m/gw-01/status").kind, "unknown");
  assert.throws(() => T.modemTopic("gw-01", "nope"));
});

test("fleet reducer: registry, profile topic, telemetry, acks, clearing", () => {
  const f = F.create();
  const gw = new MockGateway({ builtin: load("dkm440.json") });
  for (const [topic, text] of gw.initialMessages()) F.apply(f, topic, text);
  const m = f.modems["gw-01"];
  assert.equal(m.status.state, "online");
  assert.deepEqual(Object.keys(m.analyzers), ["an-01", "an-02"]);
  assert.equal(m.profiles.assign["an-01"], "dkm440");
  assert.equal(F.profileOf(f, "gw-01", "an-01").id, "dkm440");
  assert.equal(F.profileOf(f, "gw-01", "an-01").registers.length, 22);

  F.apply(f, "osos/m/gw-01/a/an-01/telemetry", JSON.stringify({ seq: 3, profile: "dkm440", values: { A: 1 } }));
  assert.equal(m.analyzers["an-01"].telemetry.seq, 3);

  const r = F.apply(f, "osos/m/gw-01/ack", JSON.stringify({ id: "c-1", ok: true, detail: "x" }));
  assert.deepEqual(r.ack, { mid: "gw-01", id: "c-1", ok: true, detail: "x" });

  F.apply(f, "osos/m/gw-01/a/an-01/profile", "");                       // retained message cleared
  assert.equal(F.profileOf(f, "gw-01", "an-01"), null);
  F.apply(f, "osos/m/gw-01/a/an-01/profile", "{not json");
  assert.equal(m.analyzers["an-01"].profileError, "unreadable profile JSON");
  assert.equal(F.apply(f, "osos/dkm440-gw1/telemetry", "{}").changed, false);
});

// ------------------------------------------------------------------- uploader
function sender(gw, opts) {
  opts = opts || {};
  return async (action, args) => {
    const r = gw.handle({ id: "x", action, args });
    if (opts.afterApply) opts.afterApply(action);
    return r.ack;
  };
}

test("upload: every step acked in order, then assigned", async () => {
  const gw = new MockGateway({ builtin: load("dkm440.json") });
  const progress = [];
  const prof = load("examples/sdm630.json");
  const log = await U.upload(prof, sender(gw), { assign: { analyzer: "an-02" }, onProgress: (i, n) => progress.push([i, n]) });
  assert.equal(log[0].action, "profile_begin");
  assert.equal(log[log.length - 2].action, "profile_commit");
  assert.equal(log[log.length - 1].action, "profile_assign");
  assert.equal(progress[progress.length - 1][0], progress[progress.length - 1][1]);
  assert.ok(gw.stored.has("sdm630"));
  assert.equal(gw.assign.get("an-02"), "sdm630");
  assert.equal(gw.stored.get("sdm630").profile.id, "sdm630");
  assert.deepEqual(gw.stored.get("sdm630").profile, P.normalize(prof));
});

test("upload: the first refusal stops it and the gateway keeps nothing half-done", async () => {
  const gw = new MockGateway({ builtin: load("dkm440.json") });
  const bad = { handle: c => c.action === "profile_meta" ? { ack: { id: c.id, ok: false, detail: "flash write failed" } } : gw.handle(c) };
  await assert.rejects(U.upload(load("dkm440.json"), (a, x) => Promise.resolve(bad.handle({ id: "x", action: a, args: x }).ack)),
    e => e instanceof U.UploadError && e.action === "profile_meta" && /flash write failed/.test(e.message));
  assert.equal(gw.stored.size, 0);
});

test("upload: an invalid profile never reaches the wire", async () => {
  const gw = new MockGateway();
  const p = load("dkm440.json");
  p.registers[0].type = "f16";
  await assert.rejects(U.upload(p, sender(gw)), /errors/);
  assert.equal(gw.log.length, 0);
});

test("upload: a lost ack is retried; a repeat the gateway already applied counts as done", async () => {
  const gw = new MockGateway({ builtin: load("dkm440.json") });
  let calls = 0;
  // Apply every command, but swallow the ack of the 3rd and 5th call.
  const send = async (action, args) => {
    const r = gw.handle({ id: "x", action, args });
    calls++;
    return (calls === 3 || calls === 5) ? null : r.ack;
  };
  await U.upload(load("examples/sdm630.json"), send, { retries: 2 });
  assert.ok(gw.stored.has("sdm630"));                       // repeats were refused "expected index N" and accepted as applied
  assert.ok(calls > gw.log.length - 2);
});

test("upload: a commit whose ack was lost is confirmed against the stored list", async () => {
  const gw = new MockGateway({ builtin: load("dkm440.json") });
  let lostOnce = false;
  const send = async (action, args) => {
    const r = gw.handle({ id: "x", action, args });
    if (action === "profile_commit" && !lostOnce) { lostOnce = true; return null; }
    return r.ack;
  };
  const verify = async p => gw.listing().profiles.some(x => x.id === p.id && x.rev === p.rev);
  await U.upload(load("examples/sdm630.json"), send, { verifyStored: verify });
  assert.ok(gw.stored.has("sdm630"));
  // without a way to confirm, the same situation is reported as a failure, never guessed
  const gw2 = new MockGateway({ builtin: load("dkm440.json") });
  let lost2 = false;
  await assert.rejects(U.upload(load("examples/sdm630.json"), async (a, x) => {
    const r = gw2.handle({ id: "x", action: a, args: x });
    if (a === "profile_commit" && !lost2) { lost2 = true; return null; }
    return r.ack;
  }), /no upload in progress/);
});

test("upload: no answer at all gives up after the retries", async () => {
  let n = 0;
  await assert.rejects(U.upload(load("dkm440.json"), async () => { n++; return null; }, { retries: 2 }), /did not answer/);
  assert.equal(n, 3);
});

test("upload can be cancelled between steps", async () => {
  const gw = new MockGateway();
  const ac = new AbortController();
  await assert.rejects(U.upload(load("dkm440.json"), async (a, x) => { ac.abort(); return gw.handle({ id: "x", action: a, args: x }).ack; }, { signal: ac.signal }), /cancelled/);
});

test("alreadyApplied only accepts the exact next position", () => {
  const regs = { i: 6, regs: [1, 2, 3, 4, 5, 6] };
  assert.equal(U.alreadyApplied("profile_regs", regs, "out of order, expected index 12"), true);
  assert.equal(U.alreadyApplied("profile_regs", regs, "out of order, expected index 6"), false);
  assert.equal(U.alreadyApplied("profile_meta", { off: 400, data: "x".repeat(400) }, "out of order, expected offset 800"), true);
  assert.equal(U.alreadyApplied("profile_begin", {}, "expected index 1"), false);
  assert.equal(U.alreadyApplied("profile_regs", regs, "flash write failed"), false);
});

test("AckBook matches by id and times out to null", async () => {
  const book = new Tr.AckBook(30);
  const p = book.expect("a");
  assert.equal(book.deliver({ id: "a", ok: true }), true);
  assert.deepEqual(await p, { id: "a", ok: true });
  assert.equal(book.deliver({ id: "zzz" }), false);
  assert.equal(await book.expect("b"), null);
});
