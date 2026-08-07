package com.osos.hmi.nn

import kotlin.math.exp
import kotlin.math.sqrt

// The "learning" half of custom commands: a softmax head over the frozen
// 128-d embedding, trained on-device from the user's 10-15 samples per
// symbol (plus shift augmentation). Embeddings are L2-normalized before the
// head so the learning rate is scale-free.

class Head(val nClasses: Int, val dim: Int, val w: DoubleArray, val b: DoubleArray) {

    fun predict(embed: DoubleArray): DoubleArray {
        val x = l2norm(embed)
        val z = DoubleArray(nClasses)
        for (c in 0 until nClasses) {
            var s = b[c]
            val off = c * dim
            for (i in 0 until dim) s += w[off + i] * x[i]
            z[c] = s
        }
        var mx = z[0]
        for (v in z) if (v > mx) mx = v
        var sum = 0.0
        for (c in z.indices) { z[c] = exp(z[c] - mx); sum += z[c] }
        for (c in z.indices) z[c] /= sum
        return z
    }

    companion object {
        fun l2norm(v: DoubleArray): DoubleArray {
            var n = 0.0
            for (x in v) n += x * x
            n = sqrt(n)
            if (n == 0.0) return v.copyOf()
            val out = DoubleArray(v.size)
            for (i in v.indices) out[i] = v[i] / n
            return out
        }
    }
}

object HeadTrainer {

    // Small translations of the 28x28 grid — cheap augmentation that makes
    // 10-15 samples behave like ~100.
    val SHIFTS = listOf(
        0 to 0, 1 to 0, -1 to 0, 0 to 1, 0 to -1,
        2 to 0, -2 to 0, 0 to 2, 0 to -2,
    )

    fun shift(grid: IntArray, dx: Int, dy: Int): IntArray {
        val out = IntArray(784)
        for (y in 0 until 28) {
            val sy = y - dy
            if (sy < 0 || sy > 27) continue
            for (x in 0 until 28) {
                val sx = x - dx
                if (sx < 0 || sx > 27) continue
                out[y * 28 + x] = grid[sy * 28 + sx]
            }
        }
        return out
    }

    // embedsByClass[c] = augmented embeddings for class c. Needs >= 2 classes
    // (a 1-class softmax is degenerate — the caller falls back to cosine).
    fun train(
        embedsByClass: List<List<DoubleArray>>,
        epochs: Int = 300,
        lr0: Double = 0.5,
        l2: Double = 1e-3,
    ): Head? {
        val n = embedsByClass.size
        if (n < 2) return null
        val dim = embedsByClass.first().firstOrNull()?.size ?: return null

        val xs = ArrayList<DoubleArray>()
        val ys = ArrayList<Int>()
        embedsByClass.forEachIndexed { c, list ->
            list.forEach { e ->
                xs.add(Head.l2norm(e))
                ys.add(c)
            }
        }
        if (xs.isEmpty()) return null

        val w = DoubleArray(n * dim)
        val b = DoubleArray(n)
        val order = xs.indices.toMutableList()
        val rnd = java.util.Random(42)

        for (epoch in 0 until epochs) {
            val lr = lr0 / (1.0 + 0.02 * epoch)
            order.shuffle(rnd)
            for (idx in order) {
                val x = xs[idx]
                val y = ys[idx]
                // p = softmax(Wx + b)
                val z = DoubleArray(n)
                for (c in 0 until n) {
                    var s = b[c]
                    val off = c * dim
                    for (i in 0 until dim) s += w[off + i] * x[i]
                    z[c] = s
                }
                var mx = z[0]
                for (v in z) if (v > mx) mx = v
                var sum = 0.0
                for (c in 0 until n) { z[c] = exp(z[c] - mx); sum += z[c] }
                for (c in 0 until n) z[c] /= sum
                // gradient step: dL/dz = p - onehot(y)
                for (c in 0 until n) {
                    val g = z[c] - (if (c == y) 1.0 else 0.0)
                    val off = c * dim
                    for (i in 0 until dim) {
                        w[off + i] -= lr * (g * x[i] + l2 * w[off + i])
                    }
                    b[c] -= lr * g
                }
            }
        }
        return Head(n, dim, w, b)
    }
}
