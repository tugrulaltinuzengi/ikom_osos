// Drawing pad + MNIST-style preprocessing.
// MNIST digits are white-on-black, size-normalized to fit 20x20 preserving
// aspect ratio, then centered by center of mass in a 28x28 field. We reproduce
// that so the net sees inputs from (close to) its training distribution.
"use strict";

const Pad = (() => {
  const canvas = document.getElementById("pad");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const preview = document.getElementById("preview");
  const pctx = preview.getContext("2d");

  const SIZE = 280, STROKE = 20, INK_MIN = 30;
  let drawing = false, hasInk = false, idleTimer = null;
  let onDone = null; // callback(grid Uint8Array(784)) fired after pen-up idle

  function reset() {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, SIZE, SIZE);
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = STROKE;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    hasInk = false;
    clearTimeout(idleTimer);
    pctx.clearRect(0, 0, 28, 28);
  }

  function pos(ev) {
    const r = canvas.getBoundingClientRect();
    return [(ev.clientX - r.left) * (SIZE / r.width),
            (ev.clientY - r.top) * (SIZE / r.height)];
  }

  canvas.addEventListener("pointerdown", ev => {
    ev.preventDefault();
    clearTimeout(idleTimer);
    drawing = true;
    hasInk = true;
    canvas.setPointerCapture(ev.pointerId);
    const [x, y] = pos(ev);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 0.01, y + 0.01); // dot for a tap
    ctx.stroke();
  });
  canvas.addEventListener("pointermove", ev => {
    if (!drawing) return;
    const [x, y] = pos(ev);
    ctx.lineTo(x, y);
    ctx.stroke();
  });
  function penUp() {
    if (!drawing) return;
    drawing = false;
    // wait for possible extra strokes (4, 5, 7 are usually multi-stroke)
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      const grid = toMnist();
      if (grid && onDone) onDone(grid);
    }, 650);
  }
  canvas.addEventListener("pointerup", penUp);
  canvas.addEventListener("pointercancel", penUp);

  // 280x280 ink -> 784 bytes, MNIST-style. Returns null if too little ink.
  function toMnist() {
    const img = ctx.getImageData(0, 0, SIZE, SIZE).data;
    const gray = new Float32Array(SIZE * SIZE);
    let minX = SIZE, minY = SIZE, maxX = -1, maxY = -1;
    for (let y = 0; y < SIZE; y++) {
      for (let x = 0; x < SIZE; x++) {
        const v = img[(y * SIZE + x) * 4]; // white ink on black: R channel
        gray[y * SIZE + x] = v;
        if (v > 25) {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX < 0) return null;
    let ink = 0;
    for (let i = 0; i < gray.length; i++) if (gray[i] > 25) ink++;
    if (ink < INK_MIN) return null;

    const bw = maxX - minX + 1, bh = maxY - minY + 1;
    const scale = 20 / Math.max(bw, bh);
    const tw = Math.max(1, Math.round(bw * scale));
    const th = Math.max(1, Math.round(bh * scale));

    // block-average downscale of the bounding box to tw x th
    const small = new Float32Array(tw * th);
    for (let ty = 0; ty < th; ty++) {
      const y0 = minY + (ty / th) * bh, y1 = minY + ((ty + 1) / th) * bh;
      for (let tx = 0; tx < tw; tx++) {
        const x0 = minX + (tx / tw) * bw, x1 = minX + ((tx + 1) / tw) * bw;
        let sum = 0, n = 0;
        for (let y = Math.floor(y0); y < Math.ceil(y1) && y <= maxY; y++) {
          for (let x = Math.floor(x0); x < Math.ceil(x1) && x <= maxX; x++) {
            sum += gray[y * SIZE + x];
            n++;
          }
        }
        small[ty * tw + tx] = n ? sum / n : 0;
      }
    }

    // center of mass of the scaled glyph
    let m = 0, mx = 0, my = 0;
    for (let y = 0; y < th; y++) {
      for (let x = 0; x < tw; x++) {
        const v = small[y * tw + x];
        m += v; mx += v * x; my += v * y;
      }
    }
    const cx = mx / m, cy = my / m;
    let offX = Math.round(14 - cx - 0.5), offY = Math.round(14 - cy - 0.5);
    offX = Math.min(Math.max(offX, 0), 28 - tw);
    offY = Math.min(Math.max(offY, 0), 28 - th);

    const grid = new Uint8Array(784);
    for (let y = 0; y < th; y++) {
      for (let x = 0; x < tw; x++) {
        const v = Math.min(255, Math.round(small[y * tw + x]));
        grid[(y + offY) * 28 + (x + offX)] = v;
      }
    }
    renderPreview(grid);
    return grid;
  }

  function renderPreview(grid) {
    const im = pctx.createImageData(28, 28);
    for (let i = 0; i < 784; i++) {
      im.data[i * 4] = im.data[i * 4 + 1] = im.data[i * 4 + 2] = grid[i];
      im.data[i * 4 + 3] = 255;
    }
    pctx.putImageData(im, 0, 0);
  }

  reset();
  return {
    clear: reset,
    setOnDone: cb => { onDone = cb; },
    get hasInk() { return hasInk; },
  };
})();
