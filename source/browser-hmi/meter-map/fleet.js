// What the page knows about the fleet, built from MQTT messages. No DOM, no I/O.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./topics.js"), require("./profile.js"));
  else root.OsosFleet = factory(root.OsosTopics, root.OsosProfile);
})(typeof self !== "undefined" ? self : this, function (T, P) {
  "use strict";

  function create() { return { modems: {} }; }

  function modem(f, mid) {
    return f.modems[mid] || (f.modems[mid] = { mid, status: null, profiles: null, analyzers: {} });
  }
  function analyzer(f, mid, aid) {
    const m = modem(f, mid);
    return m.analyzers[aid] || (m.analyzers[aid] = {
      id: aid, host: "", unit: 0, interval: 0, status: null, telemetry: null, profile: null, profileError: null,
    });
  }

  // `text` is the raw payload. Returns {changed, ack} - ack is set for ack messages,
  // which are events rather than state.
  function apply(f, topic, text) {
    const t = T.parse(topic);
    if (t.kind !== "modem" && t.kind !== "analyzer") return { changed: false };

    if (t.kind === "analyzer" && t.leaf === "profile") {
      const a = analyzer(f, t.mid, t.aid);
      if (!text || !text.trim()) { a.profile = null; a.profileError = null; return { changed: true }; }
      try {
        const p = JSON.parse(text);
        a.profile = P.normalize(p);
        a.profileError = P.errorsOf(P.validate(a.profile)).length ? "profile on the gateway does not validate" : null;
      } catch (e) {
        a.profile = null; a.profileError = "unreadable profile JSON";
      }
      return { changed: true };
    }

    let body;
    try { body = text && text.trim() ? JSON.parse(text) : null; } catch (e) { return { changed: false }; }
    if (body === null) return { changed: false };

    if (t.kind === "modem") {
      const m = modem(f, t.mid);
      switch (t.leaf) {
        case "ack": return { changed: false, ack: { mid: t.mid, id: body.id, ok: !!body.ok, detail: body.detail || "" } };
        case "status": m.status = body; break;
        case "profiles": m.profiles = body; break;
        case "registry":
          for (const a of body.analyzers || []) {
            const e = analyzer(f, t.mid, a.id);
            e.host = a.host || ""; e.unit = a.unit || 0; e.interval = a.interval || 0;
          }
          m.loads = body.loads || null;
          break;
        default: return { changed: false };
      }
      return { changed: true };
    }
    const a = analyzer(f, t.mid, t.aid);
    if (t.leaf === "telemetry") a.telemetry = Object.assign({}, body, { receivedAt: Date.now() });
    else if (t.leaf === "status") a.status = body;
    return { changed: true };
  }

  // The profile that explains an analyzer's values: what the gateway published for it.
  function profileOf(f, mid, aid) {
    const m = f.modems[mid];
    return m && m.analyzers[aid] ? m.analyzers[aid].profile : null;
  }

  return { create, apply, modem, analyzer, profileOf };
});
