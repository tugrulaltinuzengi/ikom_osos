package com.osos.hmi.data

import com.osos.hmi.mqtt.GatewayClient
import com.osos.hmi.mqtt.Protocol
import com.osos.hmi.mqtt.TopicRouter
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONArray
import org.json.JSONObject

/**
 * The app-owned half of the metadata split: labels and folders. Writes go to
 * osos/m/{mid}/labels and osos/tree, both retained, so names and structure are
 * shared by every phone without touching modem-owned registry truth.
 */
class TreeStore(
    private val client: GatewayClient,
    private val clientId: String,
) {
    val tree = MutableStateFlow(FolderTree())

    /** Compatibility stream for older UI bits that still need only paths. */
    val folders = MutableStateFlow<List<String>>(emptyList())

    private var rev = 0

    fun applyTree(json: JSONObject) {
        val arr = json.optJSONArray("folders") ?: return
        rev = maxOf(rev, json.optInt("rev", 0))
        val paths = (0 until arr.length())
            .mapNotNull { arr.optJSONObject(it) }
            .sortedBy { it.optInt("order", 0) }
            .map { it.optString("path") }
            .filter { it.isNotEmpty() }
        setTree(FolderTree.fromPaths(paths))
    }

    fun createFolder(path: String) {
        val next = tree.value.create(path)
        if (next == tree.value) return
        setTree(next)
        publishTree()
    }

    fun renameFolder(from: String, to: String, fleet: Fleet) {
        val src = FolderTree.normalize(from)
        val dst = FolderTree.normalize(to)
        val next = tree.value.rename(src, dst)
        if (next == tree.value) return
        setTree(next)
        publishTree()
        republishAffectedLabels(fleet) { folder -> remapPrefix(folder, src, dst) }
    }

    fun moveFolder(path: String, newParent: String, fleet: Fleet) {
        val src = FolderTree.normalize(path)
        val parent = FolderTree.normalize(newParent)
        val dst = FolderTree.join(parent, src.substringAfterLast('/'))
        val next = tree.value.move(src, parent)
        if (next == tree.value) return
        setTree(next)
        publishTree()
        republishAffectedLabels(fleet) { folder -> remapPrefix(folder, src, dst) }
    }

    fun deleteFolder(path: String, fleet: Fleet) {
        val src = FolderTree.normalize(path)
        val next = tree.value.delete(src)
        if (next == tree.value) return
        setTree(next)
        publishTree()
        republishAffectedLabels(fleet) { folder ->
            if (folder == src || folder.startsWith("$src/")) "" else folder
        }
    }

    fun assign(mid: String, aid: String, name: String, folder: String, fleet: Fleet) {
        val normalizedFolder = FolderTree.normalize(folder)
        val updated = fleet.modems[mid]?.analyzers.orEmpty().mapValues { (k, v) ->
            if (k == aid) v.copy(name = name, folder = normalizedFolder) else v
        }
        if (normalizedFolder.isNotEmpty() && normalizedFolder !in tree.value.nodes) {
            setTree(tree.value.create(normalizedFolder))
            publishTree()
        }
        publishLabelsFrom(mid, updated.values.map { it.aid to (it.name to it.folder) })
    }

    private fun setTree(next: FolderTree) {
        tree.value = next
        folders.value = next.paths()
    }

    private fun republishAffectedLabels(fleet: Fleet, remap: (String) -> String) {
        fleet.modems.keys.forEach { mid ->
            val analyzers = fleet.modems[mid]?.analyzers.orEmpty().values
            if (analyzers.any { remap(it.folder) != it.folder }) publishLabels(mid, fleet, remap)
        }
    }

    private fun publishLabels(mid: String, fleet: Fleet, remap: (String) -> String = { it }) {
        val entries = fleet.modems[mid]?.analyzers.orEmpty().values.map {
            it.aid to (it.name to remap(it.folder))
        }
        publishLabelsFrom(mid, entries)
    }

    private fun publishLabelsFrom(mid: String, entries: List<Pair<String, Pair<String, String>>>) {
        val labels = JSONObject()
        entries.forEach { (aid, nf) ->
            labels.put(aid, JSONObject().put("name", nf.first).put("folder", nf.second))
        }
        client.publishRetained(
            TopicRouter.modem(mid, "labels"),
            JSONObject()
                .put("v", Protocol.VERSION)
                .put("rev", ++rev)
                .put("updatedBy", clientId)
                .put("labels", labels),
        )
    }

    private fun publishTree() {
        val arr = JSONArray()
        tree.value.paths().forEachIndexed { i, path ->
            arr.put(JSONObject().put("path", path).put("order", i))
        }
        client.publishRetained(
            TopicRouter.TREE,
            JSONObject()
                .put("v", Protocol.VERSION)
                .put("rev", ++rev)
                .put("updatedBy", clientId)
                .put("folders", arr),
        )
    }

    private fun remapPrefix(folder: String, from: String, to: String): String = when {
        folder == from -> to
        folder.startsWith("$from/") -> to + folder.removePrefix(from)
        else -> folder
    }
}