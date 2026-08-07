package com.osos.hmi.nn

import android.graphics.Bitmap
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

// Bit-exact port of www/draw.js toMnist(): 280x280 white-on-black ink ->
// 784 grayscale bytes, MNIST-style (fit longest side to 20 px with a
// block-average downscale, then center-of-mass centering in 28x28).
// The net was trained on this distribution; every constant matters.
object Preprocess {
    const val SIZE = 280
    const val STROKE = 20f
    const val INK_MIN = 30
    private const val THR = 25f

    // pixels: SIZE*SIZE ARGB ints from the drawing bitmap. Returns 784 values
    // 0..255 (divide by 255 before the net), or null if too little ink.
    fun toMnist(pixels: IntArray): IntArray? {
        val gray = FloatArray(SIZE * SIZE)
        var minX = SIZE
        var minY = SIZE
        var maxX = -1
        var maxY = -1
        for (y in 0 until SIZE) {
            for (x in 0 until SIZE) {
                val v = ((pixels[y * SIZE + x] shr 16) and 0xFF).toFloat() // R channel
                gray[y * SIZE + x] = v
                if (v > THR) {
                    if (x < minX) minX = x
                    if (x > maxX) maxX = x
                    if (y < minY) minY = y
                    if (y > maxY) maxY = y
                }
            }
        }
        if (maxX < 0) return null
        var ink = 0
        for (v in gray) if (v > THR) ink++
        if (ink < INK_MIN) return null

        val bw = maxX - minX + 1
        val bh = maxY - minY + 1
        val scale = 20.0 / max(bw, bh)
        val tw = max(1, Math.round(bw * scale).toInt())
        val th = max(1, Math.round(bh * scale).toInt())

        // block-average downscale of the bounding box to tw x th
        val small = FloatArray(tw * th)
        for (ty in 0 until th) {
            val y0 = minY + ty.toDouble() / th * bh
            val y1 = minY + (ty + 1).toDouble() / th * bh
            for (tx in 0 until tw) {
                val x0 = minX + tx.toDouble() / tw * bw
                val x1 = minX + (tx + 1).toDouble() / tw * bw
                var sum = 0f
                var n = 0
                var y = floor(y0).toInt()
                while (y < ceil(y1) && y <= maxY) {
                    var x = floor(x0).toInt()
                    while (x < ceil(x1) && x <= maxX) {
                        sum += gray[y * SIZE + x]
                        n++
                        x++
                    }
                    y++
                }
                small[ty * tw + tx] = if (n > 0) sum / n else 0f
            }
        }

        // center of mass of the scaled glyph
        var m = 0.0
        var mx = 0.0
        var my = 0.0
        for (y in 0 until th) {
            for (x in 0 until tw) {
                val v = small[y * tw + x].toDouble()
                m += v
                mx += v * x
                my += v * y
            }
        }
        val cx = mx / m
        val cy = my / m
        var offX = Math.round(14 - cx - 0.5).toInt()
        var offY = Math.round(14 - cy - 0.5).toInt()
        offX = min(max(offX, 0), 28 - tw)
        offY = min(max(offY, 0), 28 - th)

        val grid = IntArray(784)
        for (y in 0 until th) {
            for (x in 0 until tw) {
                val v = min(255, Math.round(small[y * tw + x]))
                grid[(y + offY) * 28 + (x + offX)] = v
            }
        }
        return grid
    }

    fun toInput(grid: IntArray): DoubleArray {
        val x = DoubleArray(784)
        for (i in 0 until 784) x[i] = grid[i] / 255.0
        return x
    }

    // 28x28 preview bitmap (nearest-neighbor upscaling is done by the UI).
    fun gridToBitmap(grid: IntArray): Bitmap {
        val bmp = Bitmap.createBitmap(28, 28, Bitmap.Config.ARGB_8888)
        val px = IntArray(784)
        for (i in 0 until 784) {
            val v = grid[i]
            px[i] = (0xFF shl 24) or (v shl 16) or (v shl 8) or v
        }
        bmp.setPixels(px, 0, 28, 0, 0, 28, 28)
        return bmp
    }
}
