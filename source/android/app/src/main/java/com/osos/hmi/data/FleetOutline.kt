package com.osos.hmi.data

import com.osos.hmi.model.AnalyzerKey

const val UNFILED_FOLDER = "Unfiled"

enum class HealthBadge { OK, WARN, DOWN, UNKNOWN }

sealed interface FleetRow {
    val key: String
    val depth: Int

    data class Folder(
        override val key: String,
        override val depth: Int,
        val path: String,
        val name: String,
        val expanded: Boolean,
        val meterCount: Int,
        val badge: HealthBadge,
    ) : FleetRow

    data class Modem(
        override val key: String,
        override val depth: Int,
        val mid: String,
        val folder: String,
        val analyzerCount: Int,
        val online: Boolean,
        val asleep: Boolean,
        val interval: Int,
        val loads: List<Boolean>,
        val legacy: Boolean,
        val badge: HealthBadge,
    ) : FleetRow

    data class Analyzer(
        override val key: String,
        override val depth: Int,
        val who: AnalyzerKey,
        val name: String,
        val folder: String,
        val voltageL1: Double?,
        val badge: HealthBadge,
    ) : FleetRow
}

fun flattenFleet(
    fleet: Fleet,
    tree: FolderTree,
    query: String,
    expanded: Set<String>,
): List<FleetRow> {
    val q = query.trim().lowercase()
    val analyzerFolders = fleet.allAnalyzers.map { it.folder.ifEmpty { UNFILED_FOLDER } }
    val modemOnlyFolders = fleet.modems.values
        .filter { it.analyzers.isEmpty() }
        .map { UNFILED_FOLDER }
    val outlineTree = FolderTree.fromPaths(tree.paths() + analyzerFolders + modemOnlyFolders)
    val childrenByFolder = analyzersByFolder(fleet)
    val modemsWithoutAnalyzers = fleet.modems.values.filter { it.analyzers.isEmpty() }

    val rows = mutableListOf<FleetRow>()

    fun folderMatches(path: String): Boolean =
        q.isEmpty() || path.lowercase().contains(q)

    fun analyzerMatches(a: AnalyzerEntry): Boolean =
        q.isEmpty() ||
            a.aid.lowercase().contains(q) ||
            a.mid.lowercase().contains(q) ||
            a.name.lowercase().contains(q) ||
            a.folder.lowercase().contains(q)

    fun modemMatches(mid: String, analyzers: List<AnalyzerEntry>): Boolean =
        q.isEmpty() || mid.lowercase().contains(q) || analyzers.any(::analyzerMatches)

    fun folderHasMatch(path: String): Boolean {
        if (folderMatches(path)) return true
        if (childrenByFolder[path].orEmpty().values.flatten().any(::analyzerMatches)) return true
        if (path == UNFILED_FOLDER && modemsWithoutAnalyzers.any { it.mid.lowercase().contains(q) }) return true
        return outlineTree.nodes[path]?.children.orEmpty().any(::folderHasMatch)
    }

    fun emitFolder(path: String, depth: Int) {
        if (path != FolderTree.ROOT && !folderHasMatch(path)) return
        val node = outlineTree.nodes[path] ?: return
        val isSyntheticRoot = path == FolderTree.ROOT
        val isExpanded = q.isNotEmpty() || path in expanded || isSyntheticRoot
        if (!isSyntheticRoot) {
            rows += FleetRow.Folder(
                key = "f:$path",
                depth = depth,
                path = path,
                name = node.name,
                expanded = isExpanded,
                meterCount = meterCountFor(outlineTree, childrenByFolder, path),
                badge = rollupBadge(outlineTree, childrenByFolder, path),
            )
        }
        if (!isExpanded) return

        node.children.forEach { emitFolder(it, if (isSyntheticRoot) 0 else depth + 1) }

        val byModem = childrenByFolder[path].orEmpty()
        byModem.toSortedMap().forEach { (mid, analyzers) ->
            if (!modemMatches(mid, analyzers)) return@forEach
            val modem = fleet.modems[mid] ?: return@forEach
            val visibleAnalyzers = analyzers.filter { q.isEmpty() || analyzerMatches(it) }
            rows += modem.toRow(path, if (isSyntheticRoot) depth else depth + 1, visibleAnalyzers.size)
            if (q.isNotEmpty() || "m:$path:$mid" in expanded) {
                visibleAnalyzers.sortedWith(compareBy({ it.name.lowercase() }, { it.aid }))
                    .forEach { rows += it.toRow(if (isSyntheticRoot) depth + 1 else depth + 2) }
            }
        }

        if (path == UNFILED_FOLDER) {
            modemsWithoutAnalyzers.sortedBy { it.mid.lowercase() }.forEach { modem ->
                if (q.isNotEmpty() && !modem.mid.lowercase().contains(q)) return@forEach
                rows += modem.toRow(path, if (isSyntheticRoot) depth else depth + 1, 0)
            }
        }
    }

    emitFolder(FolderTree.ROOT, 0)
    return rows
}

private fun analyzersByFolder(fleet: Fleet): Map<String, Map<String, List<AnalyzerEntry>>> =
    fleet.allAnalyzers
        .groupBy { it.folder.ifEmpty { UNFILED_FOLDER } }
        .mapValues { (_, analyzers) -> analyzers.groupBy { it.mid } }

private fun meterCountFor(
    tree: FolderTree,
    grouped: Map<String, Map<String, List<AnalyzerEntry>>>,
    path: String,
): Int =
    grouped[path].orEmpty().values.sumOf { it.size } +
        tree.nodes[path]?.children.orEmpty().sumOf { meterCountFor(tree, grouped, it) }

private fun rollupBadge(
    tree: FolderTree,
    grouped: Map<String, Map<String, List<AnalyzerEntry>>>,
    path: String,
): HealthBadge {
    val badges = grouped[path].orEmpty().values.flatten().map { it.badge() } +
        tree.nodes[path]?.children.orEmpty().map { rollupBadge(tree, grouped, it) }
    return badges.rollup()
}

private fun ModemEntry.toRow(folder: String, depth: Int, analyzerCount: Int): FleetRow.Modem =
    FleetRow.Modem(
        key = "m:$folder:$mid",
        depth = depth,
        mid = mid,
        folder = folder,
        analyzerCount = analyzerCount,
        online = status?.state == "online",
        asleep = state?.sleep == true,
        interval = state?.interval ?: 0,
        loads = state?.loads.orEmpty(),
        legacy = protocolVersion == 1,
        badge = analyzers.values.map { it.badge() }.rollup().let {
            if (status?.state == "offline") HealthBadge.DOWN else it
        },
    )

private fun AnalyzerEntry.toRow(depth: Int): FleetRow.Analyzer =
    FleetRow.Analyzer(
        key = "a:$mid:$aid",
        depth = depth,
        who = AnalyzerKey(mid, aid),
        name = name,
        folder = folder.ifEmpty { UNFILED_FOLDER },
        voltageL1 = latest?.values?.get("MainBus_Voltage_L1"),
        badge = badge(),
    )

private fun AnalyzerEntry.badge(): HealthBadge = when {
    latest?.meterOk == false -> HealthBadge.WARN
    link.equals("offline", ignoreCase = true) || link.equals("down", ignoreCase = true) -> HealthBadge.DOWN
    latest != null || link.equals("online", ignoreCase = true) || link.equals("ok", ignoreCase = true) -> HealthBadge.OK
    else -> HealthBadge.UNKNOWN
}

private fun List<HealthBadge>.rollup(): HealthBadge = when {
    any { it == HealthBadge.DOWN } -> HealthBadge.DOWN
    any { it == HealthBadge.WARN } -> HealthBadge.WARN
    any { it == HealthBadge.UNKNOWN } -> HealthBadge.UNKNOWN
    isNotEmpty() -> HealthBadge.OK
    else -> HealthBadge.UNKNOWN
}
