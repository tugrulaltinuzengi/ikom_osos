package com.osos.hmi.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FolderTreeTest {
    @Test fun pathsCreateImplicitParents() {
        val tree = FolderTree.fromPaths(listOf("Istanbul/PlantA/MCC-3"))
        assertTrue(tree.nodes.containsKey("Istanbul"))
        assertTrue(tree.nodes.containsKey("Istanbul/PlantA"))
        assertEquals(listOf("Istanbul"), tree.nodes[FolderTree.ROOT]!!.children)
    }

    @Test fun renameCarriesChildren() {
        val tree = FolderTree.fromPaths(listOf("A/B", "A/B/C")).rename("A/B", "A/D")
        assertFalse(tree.nodes.containsKey("A/B"))
        assertTrue(tree.nodes.containsKey("A/D"))
        assertTrue(tree.nodes.containsKey("A/D/C"))
    }

    @Test fun moveRejectsMovingIntoSelf() {
        val tree = FolderTree.fromPaths(listOf("A/B/C"))
        assertEquals(tree, tree.move("A/B", "A/B/C"))
    }

    @Test fun deleteRemovesSubtree() {
        val tree = FolderTree.fromPaths(listOf("A/B", "A/B/C", "A/D")).delete("A/B")
        assertFalse(tree.nodes.containsKey("A/B"))
        assertFalse(tree.nodes.containsKey("A/B/C"))
        assertTrue(tree.nodes.containsKey("A/D"))
    }
}
