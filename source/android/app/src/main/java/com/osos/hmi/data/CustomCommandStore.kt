package com.osos.hmi.data

import android.content.Context
import com.osos.hmi.nn.Head
import com.osos.hmi.nn.HeadTrainer
import com.osos.hmi.nn.Mlp
import com.osos.hmi.nn.Preprocess
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

// Replaces localStorage["osos_custom_cmds_v1"]: persists {name, actionKey,
// samples[784]} to a JSON file; embeddings and the trained head are always
// recomputed from samples on load (same rule as hmi.js).
class CustomCommandStore(
    private val ctx: Context,
    private val mlp: Mlp,
    private val scope: CoroutineScope,
) {
    data class Cmd(val name: String, val actionKey: String, val samples: List<IntArray>)

    class Runtime(
        val cmds: List<Cmd>,
        // plain (unaugmented) per-sample embeddings, for cosine matching + inspector
        val embeds: List<List<DoubleArray>>,
        val head: Head?,          // null until >= 2 commands exist
        val trainedOn: Int,       // total augmented samples the head saw
    )

    val runtime = MutableStateFlow(Runtime(emptyList(), emptyList(), null, 0))
    val rebuilding = MutableStateFlow(false)

    private val file = File(ctx.filesDir, "custom_cmds.json")
    private val mutex = Mutex()

    fun load() = rebuild(loadFile())

    fun add(name: String, actionKey: String, samples: List<IntArray>) {
        val cmds = loadFile().filter { it.name != name } + Cmd(name, actionKey, samples)
        saveFile(cmds)
        rebuild(cmds)
    }

    fun remove(name: String) {
        val cmds = loadFile().filter { it.name != name }
        saveFile(cmds)
        rebuild(cmds)
    }

    private fun rebuild(cmds: List<Cmd>) {
        scope.launch(Dispatchers.Default) {
            mutex.withLock {
                rebuilding.value = true
                try {
                    val embeds = cmds.map { cmd ->
                        cmd.samples.map { mlp.embed(Preprocess.toInput(it)) }
                    }
                    var trainedOn = 0
                    val head = if (cmds.size >= 2) {
                        val aug = cmds.map { cmd ->
                            cmd.samples.flatMap { s ->
                                HeadTrainer.SHIFTS.map { (dx, dy) ->
                                    mlp.embed(Preprocess.toInput(HeadTrainer.shift(s, dx, dy)))
                                }
                            }.also { trainedOn += it.size }
                        }
                        HeadTrainer.train(aug)
                    } else null
                    runtime.value = Runtime(cmds, embeds, head, trainedOn)
                } finally {
                    rebuilding.value = false
                }
            }
        }
    }

    private fun loadFile(): List<Cmd> {
        if (!file.exists()) return emptyList()
        return try {
            val arr = JSONArray(file.readText())
            (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                val js = o.getJSONArray("samples")
                val samples = (0 until js.length()).map { si ->
                    val ja = js.getJSONArray(si)
                    IntArray(784) { pi -> ja.getInt(pi) }
                }
                Cmd(o.getString("name"), o.getString("actionKey"), samples)
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun saveFile(cmds: List<Cmd>) {
        val arr = JSONArray()
        cmds.forEach { cmd ->
            val js = JSONArray()
            cmd.samples.forEach { s ->
                val ja = JSONArray()
                s.forEach { ja.put(it) }
                js.put(ja)
            }
            arr.put(JSONObject().put("name", cmd.name).put("actionKey", cmd.actionKey).put("samples", js))
        }
        file.writeText(arr.toString())
    }
}
