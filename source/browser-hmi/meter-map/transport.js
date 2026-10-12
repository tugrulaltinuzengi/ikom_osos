// How the page talks to the fleet.
//
// Two transports, one interface:
//   mqtt     a browser, over MQTT-on-WebSocket (same broker settings as the HMI)
//   android  the OSOS app's WebView; the app owns the broker connection and
//            hands messages across the OsosAndroid bridge
//
//   t.onMessage((topic, text) => ...)   every message on the subscribed topics
//   t.onState(connected => ...)
//   t.send(mid, action, args) -> Promise<{ok, detail}|null>   null == no ack in time
//   t.connect()
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./topics.js"));
  else root.OsosTransport = factory(root.OsosTopics);
})(typeof self !== "undefined" ? self : this, function (T) {
  "use strict";

  const ACK_TIMEOUT_MS = 10000;

  // Matches acks to commands by id; shared by both transports.
  class AckBook {
    constructor(timeoutMs) { this.timeoutMs = timeoutMs || ACK_TIMEOUT_MS; this.pending = new Map(); }
    expect(id) {
      return new Promise(resolve => {
        const timer = setTimeout(() => { this.pending.delete(id); resolve(null); }, this.timeoutMs);
        this.pending.set(id, ack => { clearTimeout(timer); this.pending.delete(id); resolve(ack); });
      });
    }
    deliver(ack) { const f = this.pending.get(ack.id); if (f) f(ack); return !!f; }
  }

  const newId = () => "c-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);

  function mqttTransport(cfg, mqttLib) {
    const subs = [];
    const states = [];
    const acks = new AckBook();
    let client = null;
    const filters = [
      "osos/m/+/status", "osos/m/+/registry", "osos/m/+/profiles", "osos/m/+/ack",
      "osos/m/+/a/+/status", "osos/m/+/a/+/profile", "osos/m/+/a/+/telemetry",
    ];
    return {
      kind: "mqtt",
      onMessage(cb) { subs.push(cb); },
      onState(cb) { states.push(cb); },
      connect() {
        client = mqttLib.connect(cfg.wssUrl, {
          username: cfg.username || undefined, password: cfg.password || undefined,
          clientId: "mapui-" + Math.random().toString(16).slice(2, 10),
          keepalive: 30, clean: true, reconnectPeriod: 3000,
        });
        client.on("connect", () => { client.subscribe(filters, { qos: 1 }); states.forEach(f => f(true)); });
        client.on("close", () => states.forEach(f => f(false)));
        client.on("message", (topic, payload) => {
          const text = payload.toString();
          const t = T.parse(topic);
          if (t.kind === "modem" && t.leaf === "ack") {
            try { const a = JSON.parse(text); acks.deliver(a); } catch (e) { /* not an ack */ }
          }
          subs.forEach(f => f(topic, text));
        });
      },
      send(mid, action, args) {
        const id = newId();
        const wait = acks.expect(id);
        client.publish(T.modemTopic(mid, "cmd"), JSON.stringify({ id, action, args }), { qos: 1 });
        return wait;
      },
    };
  }

  // The Android app injects window.OsosAndroid:
  //   send(mid, action, argsJson) -> id      publishes the command
  //   snapshot() -> JSON {topic: payload}     retained profile/registry/status topics already received
  //   connected() -> bool
  // and calls OsosBridge.onMessage(topic, text) / OsosBridge.onState(bool) as things arrive.
  function androidTransport(android, bridgeHost) {
    const subs = [];
    const states = [];
    const acks = new AckBook();
    bridgeHost.OsosBridge = {
      onMessage(topic, text) {
        const t = T.parse(topic);
        if (t.kind === "modem" && t.leaf === "ack") {
          try { acks.deliver(JSON.parse(text)); } catch (e) { /* ignore */ }
        }
        subs.forEach(f => f(topic, text));
      },
      onState(ok) { states.forEach(f => f(!!ok)); },
    };
    return {
      kind: "android",
      onMessage(cb) { subs.push(cb); },
      onState(cb) { states.push(cb); },
      connect() {
        let snap = {};
        try { snap = JSON.parse(android.snapshot()); } catch (e) { /* none yet */ }
        states.forEach(f => f(!!android.connected()));
        for (const [topic, text] of Object.entries(snap)) subs.forEach(f => f(topic, text));
      },
      send(mid, action, args) {
        const id = android.send(mid, action, JSON.stringify(args));
        return acks.expect(String(id));
      },
    };
  }

  function create(env) {
    env = env || (typeof window !== "undefined" ? window : {});
    if (env.OsosTransportOverride) {                                      // tests
      const o = env.OsosTransportOverride;
      return typeof o === "function" ? o() : o;
    }
    if (env.OsosAndroid) return androidTransport(env.OsosAndroid, env);
    const cfg0 = env.OSOS_CONFIG || {};
    const qs = new URLSearchParams(env.location ? env.location.search : "");
    const cfg = {
      wssUrl: qs.get("wss") || cfg0.wssUrl || "wss://broker.emqx.io:8084/mqtt",
      username: qs.get("user") ?? cfg0.username ?? "",
      password: qs.get("pass") ?? cfg0.password ?? "",
    };
    if (!env.mqtt) throw new Error("mqtt.min.js is not loaded");
    return mqttTransport(cfg, env.mqtt);
  }

  return { create, AckBook, mqttTransport, androidTransport, newId };
});
