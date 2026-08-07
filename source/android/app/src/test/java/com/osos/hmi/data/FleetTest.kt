package com.osos.hmi.data

import com.osos.hmi.mqtt.Route
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FleetTest {
    private val registry = JSONObject(
        """{"v":2,"rev":1,"loads":{"channels":4},"analyzers":[
             {"id":"an-01","host":"192.169.10.74","port":502,"unit":1,"interval":5}]}"""
    )
    private val telemetry = JSONObject(
        """{"v":2,"ts":"2026-08-04T09:30:05Z","seq":7,"buffered":false,
            "meter_ok":true,"values":{"MainBus_Voltage_L1":231.4}}"""
    )

    @Test fun registryCreatesAnalyzer() {
        val f = Fleet().reduce(Route.ModemRegistry("gw-01"), registry)
        assertEquals(setOf("an-01"), f.modems["gw-01"]!!.analyzers.keys)
        assertEquals("192.169.10.74", f.analyzer("gw-01", "an-01")!!.host)
    }

    @Test fun labelsNameAndFolderMergeOntoRegistry() {
        val f = Fleet()
            .reduce(Route.ModemRegistry("gw-01"), registry)
            .reduce(
                Route.ModemLabels("gw-01"),
                JSONObject("""{"v":2,"rev":1,"labels":{"an-01":{"name":"Ana Pano","folder":"Saha-1"}}}"""),
            )
        val a = f.analyzer("gw-01", "an-01")!!
        assertEquals("Ana Pano", a.name)
        assertEquals("Saha-1", a.folder)
    }

    // Labels may arrive before registry - retained delivery order is not
    // guaranteed. The name must survive and attach when registry lands.
    @Test fun labelsBeforeRegistryStillApply() {
        val f = Fleet()
            .reduce(
                Route.ModemLabels("gw-01"),
                JSONObject("""{"v":2,"rev":1,"labels":{"an-01":{"name":"Ana Pano","folder":"Saha-1"}}}"""),
            )
            .reduce(Route.ModemRegistry("gw-01"), registry)
        assertEquals("Ana Pano", f.analyzer("gw-01", "an-01")!!.name)
    }

    @Test fun unlabelledAnalyzerFallsBackToItsId() {
        val f = Fleet().reduce(Route.ModemRegistry("gw-01"), registry)
        assertEquals("an-01", f.analyzer("gw-01", "an-01")!!.name)
    }

    @Test fun telemetryAttachesToAnalyzer() {
        val f = Fleet()
            .reduce(Route.ModemRegistry("gw-01"), registry)
            .reduce(Route.AnalyzerTelemetry("gw-01", "an-01"), telemetry)
        assertEquals(231.4, f.analyzer("gw-01", "an-01")!!.latest!!.values["MainBus_Voltage_L1"]!!, 1e-9)
    }

    // Telemetry from an analyzer absent from the registry must still show.
    // Losing readings because a retained registry was missing would be worse
    // than showing an unnamed analyzer.
    @Test fun telemetryForUnknownAnalyzerCreatesIt() {
        val f = Fleet().reduce(Route.AnalyzerTelemetry("gw-02", "an-99"), telemetry)
        assertTrue(f.analyzer("gw-02", "an-99") != null)
    }

    @Test fun modemStateCarriesSleepAndLoads() {
        val f = Fleet().reduce(
            Route.ModemState("gw-01"),
            JSONObject("""{"v":2,"sleep":true,"interval":300,"loads":[false,false,true,false],"since":"x"}"""),
        )
        val st = f.modems["gw-01"]!!.state!!
        assertTrue(st.sleep)
        assertEquals(listOf(false, false, true, false), st.loads)
    }

    @Test fun unknownMajorVersionIsFlagged() {
        val f = Fleet().reduce(
            Route.ModemStatus("gw-01"),
            JSONObject("""{"v":99,"state":"online"}"""),
        )
        assertTrue(f.modems["gw-01"]!!.unsupportedVersion)
    }

    @Test fun legacyTelemetryBecomesSingleAnalyzerModem() {
        val f = Fleet().reduce(
            Route.LegacyTelemetry("dkm440-gw1"),
            JSONObject("""{"ts":"x","seq":1,"buffered":false,"meter_ok":true,"values":{"Supply_Voltage":13.2}}"""),
        )
        val m = f.modems["dkm440-gw1"]!!
        assertEquals(1, m.protocolVersion)
        assertEquals(setOf(Fleet.LEGACY_AID), m.analyzers.keys)
    }

    // The registry is authoritative hardware truth. A modem that comes back
    // with fewer analyzers has genuinely lost them, and the retained registry
    // is the only signal - so entries missing from it must disappear, or a
    // decommissioned analyzer haunts the tree forever showing "—".
    @Test fun registryShrinkDropsVanishedAnalyzers() {
        val three = JSONObject(
            """{"v":2,"analyzers":[{"id":"an-01","host":"h","unit":1,"interval":5},
                                   {"id":"an-02","host":"h","unit":1,"interval":5},
                                   {"id":"an-03","host":"h","unit":1,"interval":5}]}"""
        )
        val f = Fleet()
            .reduce(Route.ModemRegistry("gw-01"), three)
            .reduce(Route.ModemRegistry("gw-01"), registry)
        assertEquals(setOf("an-01"), f.modems["gw-01"]!!.analyzers.keys)
    }

    // ...but telemetry-discovered analyzers are not in any registry, so a
    // registry update must not delete them.
    @Test fun registryDoesNotDropTelemetryDiscoveredAnalyzers() {
        val f = Fleet()
            .reduce(Route.AnalyzerTelemetry("gw-01", "an-99"), telemetry)
            .reduce(Route.ModemRegistry("gw-01"), registry)
        assertTrue(f.analyzer("gw-01", "an-99") != null)
        assertTrue(f.analyzer("gw-01", "an-01") != null)
    }

    @Test fun unrelatedTopicIsIgnored() {
        val f = Fleet().reduce(Route.Unknown("osos/nope"), JSONObject())
        assertTrue(f.modems.isEmpty())
    }

    @Test fun analyzerLookupMissesCleanly() =
        assertNull(Fleet().analyzer("nope", "nope"))
}
