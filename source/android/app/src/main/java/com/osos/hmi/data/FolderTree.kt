package com.osos.hmi.data

data class FolderNode(
    val path: String,
    val name: String,
    val parent: String?,
    val children: List<String> = emptyList(),
    val explicit: Boolean = true,
)

data class FolderTree(val nodes: Map<String, FolderNode> = mapOf(ROOT to rootNode())) {
    fun paths(explicitOnly: Boolean = true): List<String> =
        nodes.values
            .filter { it.path != ROOT && (!explicitOnly || it.explicit) }
            .sortedBy { it.path.lowercase() }
            .map { it.path }

    fun create(path: String): FolderTree = fromPaths(paths() + normalize(path))

    fun rename(from: String, to: String): FolderTree {
        val src = normalize(from)
        val dst = normalize(to)
        if (src.isEmpty() || dst.isEmpty() || src == dst) return this
        return fromPaths(paths().map { path ->
            when {
                path == src -> dst
                path.startsWith("$src/") -> dst + path.removePrefix(src)
                else -> path
            }
        })
    }

    fun move(path: String, newParent: String): FolderTree {
        val src = normalize(path)
        val parent = normalize(newParent)
        if (src.isEmpty() || parent == src || parent.startsWith("$src/")) return this
        val dst = join(parent, src.substringAfterLast('/'))
        return rename(src, dst)
    }

    fun delete(path: String): FolderTree {
        val src = normalize(path)
        if (src.isEmpty()) return this
        return fromPaths(paths().filterNot { it == src || it.startsWith("$src/") })
    }

    companion object {
        const val ROOT = ""

        fun fromPaths(paths: Iterable<String>): FolderTree {
            val explicit = paths.map(::normalize).filter { it.isNotEmpty() }.toSet()
            val all = linkedSetOf(ROOT)
            explicit.forEach { path ->
                var cur = ""
                segments(path).forEach { part ->
                    cur = join(cur, part)
                    all += cur
                }
            }

            val children = all.drop(1).groupBy { parentOf(it) ?: ROOT }
            val nodes = all.associateWith { path ->
                FolderNode(
                    path = path,
                    name = path.substringAfterLast('/').ifEmpty { "Fleet" },
                    parent = if (path == ROOT) null else parentOf(path),
                    children = children[path].orEmpty().sortedBy { it.lowercase() },
                    explicit = path == ROOT || path in explicit,
                )
            }
            return FolderTree(nodes)
        }

        fun normalize(path: String): String =
            path.split('/')
                .map { it.trim() }
                .filter { it.isNotEmpty() }
                .joinToString("/")

        fun join(parent: String, name: String): String {
            val cleanParent = normalize(parent)
            val cleanName = normalize(name).substringAfterLast('/')
            return listOf(cleanParent, cleanName).filter { it.isNotEmpty() }.joinToString("/")
        }

        private fun rootNode() = FolderNode(ROOT, "Fleet", null, explicit = true)
        private fun segments(path: String) = normalize(path).split('/').filter { it.isNotEmpty() }
        private fun parentOf(path: String): String? =
            normalize(path).substringBeforeLast('/', missingDelimiterValue = "")
    }
}
