package com.osos.hmi.data

import com.osos.hmi.mqtt.Route
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FleetOutlineTest {
    private val registry = JSONObject(
        """{"v":2,"analyzers":[
            {"id":"an-01","host":"h","unit":1,"interval":5},
            {"id":"an-02","host":"h","unit":1,"interval":5}]}"""
    )

    private val labels = JSONObject(
        """{"v":2,"labels":{
            "an-01":{"name":"Main incomer","folder":"Istanbul/PlantA/MCC-3"},
            "an-02":{"name":"Pump panel","folder":""}}}"""
    )

    @Test fun collapsedSubtreeDoesNotEmitChildren() {
        val fleet = Fleet()
            .reduce(Route.ModemRegistry("gw-01"), registry)
            .reduce(Route.ModemLabels("gw-01"), labels)
        val rows = flattenFleet(
            fleet = fleet,
            tree = FolderTree.fromPaths(listOf("Istanbul/PlantA/MCC-3")),
            query = "",
            expanded = setOf("Istanbul"),
        )

        assertTrue(rows.any { it is FleetRow.Folder && it.path == "Istanbul/PlantA" })
        assertTrue(rows.none { it is FleetRow.Folder && it.path == "Istanbul/PlantA/MCC-3" })
        assertTrue(rows.none { it is FleetRow.Analyzer && it.name == "Main incomer" })
    }

    @Test fun searchOpensOnlyMatchingPath() {
        val fleet = Fleet()
            .reduce(Route.ModemRegistry("gw-01"), registry)
            .reduce(Route.ModemLabels("gw-01"), labels)
        val rows = flattenFleet(fleet, FolderTree(), "pump", emptySet())

        assertTrue(rows.any { it is FleetRow.Folder && it.path == UNFILED_FOLDER })
        assertTrue(rows.any { it is FleetRow.Analyzer && it.name == "Pump panel" })
        assertTrue(rows.none { it is FleetRow.Analyzer && it.name == "Main incomer" })
    }

    @Test fun folderRowsCarryRolledUpCounts() {
        val fleet = Fleet()
            .reduce(Route.ModemRegistry("gw-01"), registry)
            .reduce(Route.ModemLabels("gw-01"), labels)
        val rows = flattenFleet(fleet, FolderTree.fromPaths(listOf("Istanbul")), "", setOf("Istanbul"))
        val folder = rows.filterIsInstance<FleetRow.Folder>().first { it.path == "Istanbul" }

        assertEquals(1, folder.meterCount)
    }

    @Test fun unfiledModemWithoutMetersIsAdoptable() {
        val fleet = Fleet().reduce(Route.ModemStatus("gw-99"), JSONObject("""{"v":2,"state":"online"}"""))
        val rows = flattenFleet(fleet, FolderTree(), "", setOf(UNFILED_FOLDER))

        assertTrue(rows.any { it is FleetRow.Folder && it.path == UNFILED_FOLDER })
        assertTrue(rows.any { it is FleetRow.Modem && it.mid == "gw-99" })
    }
}
