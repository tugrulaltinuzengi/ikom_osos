// Forward pass mirroring neural_net_c (src/nn.cpp + activations.cpp).
// Weights come from weights.json (base64 little-endian float32, exported by
// tools/export_weights.py from the NNC1 w.bin).
"use strict";

const NN = (() => {
  let layers = null; // [{in, out, act, W: Float32Array, b: Float32Array}]

  function b64ToF32(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Float32Array(bytes.buffer);
  }

  async function load(url) {
    const doc = await (await fetch(url)).json();
    if (doc.format !== "nnc-json-1") throw new Error("bad weights format");
    layers = doc.layers.map(l => ({
      in: l.in, out: l.out, act: l.act,
      W: b64ToF32(l.W_b64), b: b64ToF32(l.b_b64),
    }));
    return doc.arch.join("-");
  }

  // x: array of length layers[0].in, values 0..1
  function forward(x) {
    if (!layers) throw new Error("weights not loaded");
    let a = x;
    for (const l of layers) {
      const z = new Float64Array(l.out);
      for (let j = 0; j < l.out; j++) {
        let s = l.b[j];
        const row = j * l.in;
        for (let i = 0; i < l.in; i++) s += l.W[row + i] * a[i];
        z[j] = s;
      }
      if (l.act === "relu") {
        for (let j = 0; j < l.out; j++) if (z[j] < 0) z[j] = 0;
      } else if (l.act === "sigmoid") {
        for (let j = 0; j < l.out; j++) z[j] = 1 / (1 + Math.exp(-z[j]));
      } else if (l.act === "softmax") {
        let m = -Infinity;
        for (let j = 0; j < l.out; j++) if (z[j] > m) m = z[j];
        let sum = 0;
        for (let j = 0; j < l.out; j++) { z[j] = Math.exp(z[j] - m); sum += z[j]; }
        for (let j = 0; j < l.out; j++) z[j] /= sum;
      }
      a = z;
    }
    let pred = 0;
    for (let j = 1; j < a.length; j++) if (a[j] > a[pred]) pred = j;
    return { probs: a, pred, conf: a[pred] };
  }

  // Hidden-layer activations (the 128-d embedding) — used as a feature vector
  // for matching user-defined custom symbols by cosine similarity.
  function embed(x) {
    if (!layers) throw new Error("weights not loaded");
    let a = x;
    for (let li = 0; li < layers.length - 1; li++) {
      const l = layers[li];
      const z = new Float64Array(l.out);
      for (let j = 0; j < l.out; j++) {
        let s = l.b[j];
        const row = j * l.in;
        for (let i = 0; i < l.in; i++) s += l.W[row + i] * a[i];
        z[j] = l.act === "relu" ? Math.max(0, s)
             : l.act === "sigmoid" ? 1 / (1 + Math.exp(-s)) : s;
      }
      a = z;
    }
    return a;
  }

  function cosine(a, b) {
    let dot = 0, na = 0, nb = 0;
    for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
    const d = Math.sqrt(na) * Math.sqrt(nb);
    return d > 0 ? dot / d : 0;
  }

  return { load, forward, embed, cosine };
})();
