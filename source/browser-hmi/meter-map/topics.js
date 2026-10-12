// MQTT topic grammar, JS side. Counterparts: tools/osos_proto.py, TopicRouter.kt,
// commands.h - all must agree.
//
//   osos/m/{mid}/{status|registry|state|event|cmd|ack|labels|profiles}
//   osos/m/{mid}/a/{aid}/{telemetry|status|profile}
//   osos/{gwId}/{telemetry|status|event|ack|cmd}        <- legacy v1
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.OsosTopics = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const MODEM_LEAVES = ["status", "registry", "state", "event", "cmd", "ack", "labels", "profiles"];
  const ANALYZER_LEAVES = ["telemetry", "status", "profile"];
  const LEGACY_LEAVES = ["telemetry", "status", "event", "ack", "cmd"];

  const modemTopic = (mid, leaf) => {
    if (!MODEM_LEAVES.includes(leaf)) throw new Error("not a modem leaf: " + leaf);
    return `osos/m/${mid}/${leaf}`;
  };
  const analyzerTopic = (mid, aid, leaf) => {
    if (!ANALYZER_LEAVES.includes(leaf)) throw new Error("not an analyzer leaf: " + leaf);
    return `osos/m/${mid}/a/${aid}/${leaf}`;
  };

  // -> { kind: modem|analyzer|tree|legacy|unknown, mid, aid, leaf }
  function parse(topic) {
    const p = String(topic).split("/");
    const unknown = { kind: "unknown", mid: null, aid: null, leaf: null };
    if (p[0] !== "osos") return unknown;
    if (p.length === 2 && p[1] === "tree") return { kind: "tree", mid: null, aid: null, leaf: "tree" };
    if (p.length === 4 && p[1] === "m" && MODEM_LEAVES.includes(p[3])) return { kind: "modem", mid: p[2], aid: null, leaf: p[3] };
    if (p.length === 6 && p[1] === "m" && p[3] === "a" && ANALYZER_LEAVES.includes(p[5])) return { kind: "analyzer", mid: p[2], aid: p[4], leaf: p[5] };
    if (p.length === 3 && p[1] !== "m" && LEGACY_LEAVES.includes(p[2])) return { kind: "legacy", mid: p[1], aid: null, leaf: p[2] };
    return unknown;
  }

  return { modemTopic, analyzerTopic, parse, MODEM_LEAVES, ANALYZER_LEAVES };
});
