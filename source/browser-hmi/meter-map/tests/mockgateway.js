"use strict";
// A small in-memory gateway for UI and uploader tests: the same command set and
// ack texts as firmware/profile_store.h, minus the flash. (The real rules are
// tested against vectors in the C++ and Python suites; this is a stand-in so the
// page can be driven without hardware.)
(function (root, factory) {
  // The profile library is fetched lazily: in a page this file may be injected before profile.js.
  if (typeof module === "object" && module.exports) module.exports = factory(() => require("../profile.js"));
  else root.MockGateway = factory(() => root.OsosProfile);
})(typeof self !== "undefined" ? self : this, function (lib) {
  "use strict";

  class MockGateway {
    constructor(opts) {
      opts = opts || {};
      this.mid = opts.mid || "gw-01";
      this.analyzers = opts.analyzers || ["an-01", "an-02"];
      this.stored = new Map();
      this.assign = new Map();
      this.up = null;
      this.log = [];
      this.dropAcks = 0;             // swallow this many acks (simulate a lossy link)
      this.dropAfterApply = false;   // ...but apply the command first
      this.meter = opts.meter || (() => null);   // (fc, addr, words) -> words|null
      this.builtin = opts.builtin || null;
    }

    listing() {
      const profiles = [...this.stored.values()].map(s => ({ id: s.profile.id, rev: s.rev, n: s.n, name: s.name }));
      if (this.builtin && !this.stored.has(this.builtin.id)) {
        profiles.unshift({ id: this.builtin.id, rev: this.builtin.rev || 1, n: this.builtin.registers.length, name: this.builtin.name, builtin: true });
      }
      const assign = {};
      for (const a of this.analyzers) assign[a] = this.assign.get(a) || (this.builtin ? this.builtin.id : "");
      return { v: 2, profiles, assign, cap: { regs: 48, profiles: 6, blob: 8192, free: 700000 } };
    }

    blobFor(aid) {
      const id = this.assign.get(aid) || (this.builtin && this.builtin.id);
      const s = this.stored.get(id);
      if (s) return lib().canonicalJson(s.profile);
      return this.builtin && id === this.builtin.id ? lib().canonicalJson(this.builtin) : "";
    }

    // -> { ack: {id, ok, detail}|null, publish: [[topic, text, retained]] }
    handle(cmd) {
      const a = cmd.args || {};
      let ok = false, detail = "";
      const pub = [];
      const fail = d => { ok = false; detail = d; };
      switch (cmd.action) {
        case "profile_begin":
          this.up = { id: a.id, name: a.name, rev: a.rev, n: a.n, blob_len: a.blob_len, regs: [], blob: "" };
          ok = true; detail = `upload ${a.id} started`; break;
        case "profile_regs":
          if (!this.up || this.up.id !== a.id) fail("no upload in progress for that id");
          else if (a.i !== this.up.regs.length) fail(`out of order, expected index ${this.up.regs.length}`);
          else { this.up.regs.push(...a.regs); ok = true; detail = `${this.up.regs.length}/${this.up.n} regs`; }
          break;
        case "profile_meta":
          if (!this.up || this.up.id !== a.id) fail("no upload in progress for that id");
          else if (a.off !== this.up.blob.length) fail(`out of order, expected offset ${this.up.blob.length}`);
          else { this.up.blob += a.data; ok = true; detail = `${this.up.blob.length}/${this.up.blob_len} bytes`; }
          break;
        case "profile_commit": {
          const u = this.up;
          if (!u || u.id !== a.id) fail("no upload in progress for that id");
          else if (u.regs.length !== u.n) fail(`incomplete: ${u.regs.length}/${u.n} regs`);
          else if (u.blob.length !== u.blob_len) fail(`incomplete: ${u.blob.length}/${u.blob_len} bytes`);
          else {
            this.stored.set(u.id, { profile: JSON.parse(u.blob), rev: u.rev, n: u.n, name: u.name, regs: u.regs });
            this.up = null; ok = true; detail = `stored ${u.id} rev ${u.rev} (${u.n} regs)`;
            pub.push(...this.profilePublishes(u.id));
          }
          break;
        }
        case "profile_assign":
          if (!this.analyzers.includes(a.analyzer)) fail(`no such analyzer: ${a.analyzer}`);
          else if (!this.stored.has(a.profile) && !(this.builtin && this.builtin.id === a.profile)) fail(`no such profile: ${a.profile}`);
          else { this.assign.set(a.analyzer, a.profile); ok = true; detail = `${a.analyzer} reads as ${a.profile}`; pub.push(...this.profilePublishes(null, a.analyzer)); }
          break;
        case "profile_delete": {
          const users = [...this.assign].filter(([, p]) => p === a.id).map(([x]) => x);
          if (!this.stored.has(a.id)) fail("no such stored profile");
          else if (users.length) fail(`in use by ${users.join(", ")}`);
          else { this.stored.delete(a.id); ok = true; detail = `deleted ${a.id}`; pub.push(...this.profilePublishes(a.id)); }
          break;
        }
        case "profile_list": ok = true; detail = "listing republished"; pub.push(this.listPublish()); break;
        case "profile_test": {
          if (!this.analyzers.includes(a.analyzer)) { fail(`no such analyzer: ${a.analyzer}`); break; }
          const words = a.count ? a.count : lib().TYPES[a.type || "f32"][0];
          const got = this.meter(a.fc || 3, a.address, words);
          if (!got) { fail("read failed (modbus exception 0x02)"); break; }
          ok = true;
          detail = "raw=" + got.map(w => w.toString(16).toUpperCase().padStart(4, "0")).join(" ");
          if (!a.count) {
            const v = lib().decodeWords(got, a.type || "f32", a.word_order, a.byte_order, a.scale, a.offset);
            detail += v === null ? " value=n/a (not finite)" : " value=" + v.toFixed(a.decimals === undefined ? 3 : a.decimals);
          }
          break;
        }
        default: fail("unknown action: " + cmd.action);
      }
      this.log.push({ action: cmd.action, ok, detail });
      let ack = { id: cmd.id, ok, detail };
      if (this.dropAcks > 0) { this.dropAcks--; ack = null; if (!this.dropAfterApply) { /* not applied either */ } }
      return { ack, publish: pub };
    }

    listPublish() { return [`osos/m/${this.mid}/profiles`, JSON.stringify(this.listing()), true]; }
    profilePublishes(changedId, changedAnalyzer) {
      const out = [this.listPublish()];
      for (const aid of this.analyzers) {
        const cur = this.assign.get(aid) || (this.builtin && this.builtin.id);
        if (cur === changedId || aid === changedAnalyzer) {
          out.push([`osos/m/${this.mid}/a/${aid}/profile`, this.blobFor(aid), true]);
        }
      }
      return out;
    }
    initialMessages() {
      const msgs = [
        [`osos/m/${this.mid}/status`, JSON.stringify({ v: 2, state: "online", fw: "mock", ip: "127.0.0.1", rssi: -50 }), true],
        [`osos/m/${this.mid}/registry`, JSON.stringify({ v: 2, rev: 1, loads: { channels: 4 },
          analyzers: this.analyzers.map(id => ({ id, host: "192.168.0.1", port: 502, unit: 1, interval: 5 })) }), true],
        this.listPublish(),
      ];
      for (const aid of this.analyzers) msgs.push([`osos/m/${this.mid}/a/${aid}/profile`, this.blobFor(aid), true]);
      return msgs;
    }
  }
  return MockGateway;
});
