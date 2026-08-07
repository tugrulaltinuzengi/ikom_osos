package com.osos.hmi.nn

import android.content.Context
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import kotlin.math.exp
import kotlin.math.sqrt

// Port of www/nn.js: same nnc-json-1 weight format, same forward math
// (float32 weights, float64 accumulation, W row-major [out][in]).

class Layer(val nIn: Int, val nOut: Int, val act: String, val w: FloatArray, val b: FloatArray) {

    fun apply(a: DoubleArray): DoubleArray {
        val z = DoubleArray(nOut)
        for (j in 0 until nOut) {
            var s = b[j].toDouble()
            val off = j * nIn
            for (i in 0 until nIn) s += w[off + i] * a[i]
            z[j] = s
        }
        when (act) {
            "relu" -> for (j in z.indices) if (z[j] < 0) z[j] = 0.0
            "sigmoid" -> for (j in z.indices) z[j] = 1.0 / (1.0 + exp(-z[j]))
            "softmax" -> {
                var mx = z[0]
                for (v in z) if (v > mx) mx = v
                var sum = 0.0
                for (j in z.indices) { z[j] = exp(z[j] - mx); sum += z[j] }
                for (j in z.indices) z[j] /= sum
            }
        }
        return z
    }
}

class Mlp(val layers: List<Layer>, val archLabel: String) {

    class Result(val probs: DoubleArray, val pred: Int, val conf: Double)

    fun forward(x: DoubleArray): Result {
        var a = x
        for (layer in layers) a = layer.apply(a)
        var pred = 0
        for (i in a.indices) if (a[i] > a[pred]) pred = i
        return Result(a, pred, a[pred])
    }

    // Activations of the second-to-last layer — the 128-d ReLU embedding
    // used for custom-symbol matching (nn.js embed()).
    fun embed(x: DoubleArray): DoubleArray {
        var a = x
        for (i in 0 until layers.size - 1) a = layers[i].apply(a)
        return a
    }

    companion object {
        fun cosine(a: DoubleArray, b: DoubleArray): Double {
            var dot = 0.0
            var na = 0.0
            var nb = 0.0
            for (i in a.indices) {
                dot += a[i] * b[i]
                na += a[i] * a[i]
                nb += b[i] * b[i]
            }
            return if (na == 0.0 || nb == 0.0) 0.0 else dot / (sqrt(na) * sqrt(nb))
        }

        // weights.json = tools/export_weights.py output (nnc-json-1):
        // base64 of little-endian float32, W[j*in + i].
        fun loadFromAssets(ctx: Context, name: String = "weights.json"): Mlp {
            val doc = JSONObject(ctx.assets.open(name).readBytes().decodeToString())
            require(doc.getString("format") == "nnc-json-1") { "unknown weights format" }
            val jl = doc.getJSONArray("layers")
            val layers = ArrayList<Layer>(jl.length())
            for (i in 0 until jl.length()) {
                val o = jl.getJSONObject(i)
                layers.add(
                    Layer(
                        o.getInt("in"), o.getInt("out"), o.getString("act"),
                        floats(o.getString("W_b64")), floats(o.getString("b_b64")),
                    )
                )
            }
            val arch = doc.getJSONArray("arch")
            val label = (0 until arch.length()).joinToString("-") { arch.getInt(it).toString() }
            return Mlp(layers, label)
        }

        private fun floats(b64: String): FloatArray {
            val bytes = Base64.getDecoder().decode(b64)
            val fb = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
            val out = FloatArray(fb.remaining())
            fb.get(out)
            return out
        }
    }
}
