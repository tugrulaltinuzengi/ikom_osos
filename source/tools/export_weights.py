#!/usr/bin/env python3
"""Export neural_net_c weights (NNC1 binary) to weights.json for the browser.

NNC1 layout (see neural_net_c/src/main_mnist.cpp save_weights):
    "NNC1"                      4 bytes magic
    int32 n_layers
    per layer:
        int32 in, int32 out, int32 act      (act: 0=sigmoid 1=relu 2=softmax)
        double W[out*in]                    row-major, W[j*in + i]
        double b[out]
All little-endian, raw doubles.

Output: JSON with base64-encoded little-endian float32 arrays (halves the size;
~1e-6 probability drift vs doubles is irrelevant for a 0.90 threshold).

Usage:
    python export_weights.py [--w-bin PATH] [--out PATH] [--plain]
"""
import argparse
import base64
import json
import struct
import sys
from pathlib import Path

ACT_NAMES = {0: "sigmoid", 1: "relu", 2: "softmax"}
_REPO = Path(__file__).resolve().parent.parent          # .../ikom_osos/osos_emu
DEFAULT_W_BIN = _REPO.parent / "neural_net_c" / "w.bin"  # sibling project, not absolute
DEFAULT_OUT = _REPO / "www" / "weights.json"


def read_nnc1(path):
    raw = Path(path).read_bytes()
    if raw[:4] != b"NNC1":
        sys.exit(f"error: {path} has no NNC1 magic (got {raw[:4]!r})")
    off = 4
    (n_layers,) = struct.unpack_from("<i", raw, off)
    off += 4
    layers = []
    for li in range(n_layers):
        n_in, n_out, act = struct.unpack_from("<iii", raw, off)
        off += 12
        w = struct.unpack_from(f"<{n_out * n_in}d", raw, off)
        off += 8 * n_out * n_in
        b = struct.unpack_from(f"<{n_out}d", raw, off)
        off += 8 * n_out
        layers.append({"in": n_in, "out": n_out, "act": act, "W": w, "b": b})
    if off != len(raw):
        sys.exit(f"error: {len(raw) - off} trailing bytes after layer {n_layers}")
    return layers


def f32_b64(values):
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode("ascii")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w-bin", default=DEFAULT_W_BIN)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--plain", action="store_true",
                    help="emit readable number arrays instead of base64 (debugging)")
    args = ap.parse_args()

    layers = read_nnc1(args.w_bin)
    arch = [layers[0]["in"]] + [l["out"] for l in layers]
    acts = [ACT_NAMES.get(l["act"], f"unknown{l['act']}") for l in layers]

    out_layers = []
    for l in layers:
        entry = {"in": l["in"], "out": l["out"], "act": ACT_NAMES.get(l["act"])}
        if args.plain:
            entry["W"] = [round(v, 9) for v in l["W"]]
            entry["b"] = [round(v, 9) for v in l["b"]]
        else:
            entry["W_b64"] = f32_b64(l["W"])
            entry["b_b64"] = f32_b64(l["b"])
        out_layers.append(entry)

    doc = {"format": "nnc-json-1", "arch": arch, "acts": acts, "layers": out_layers}
    out_path = Path(args.out)
    out_path.write_text(json.dumps(doc, separators=(",", ":")), encoding="ascii")
    print(f"{args.w_bin} -> {out_path}")
    print(f"arch {'-'.join(map(str, arch))}, acts {acts}, "
          f"{out_path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
