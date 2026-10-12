package com.osos.hmi.model

import com.osos.hmi.data.Fleet
import com.osos.hmi.mqtt.Route
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MeterProfileTest {
    private val sdm = JSONObject(
        """{"schema":1,"id":"sdm630","name":"Eastron SDM630","rev":3,
            "registers":[
              {"key":"Voltage_L1","address":0,"unit":"V","label":"Voltage L1","decimals":2},
              {"key":"Energy_Import","address":72,"unit":"kWh","label":"Import energy","decimals":0},
              {"key":"PF","address":30}],
            "views":[{"id":"overview","label":"overview","keys":["Voltage_L1","PF"]},
                     {"id":"energy","label":"energy","keys":["Energy_Import"]}]}"""
    )

    @Test fun parsesLabelsUnitsAndViews() {
        val p = MeterProfile.parse(sdm)!!
        assertEquals("sdm630", p.id)
        assertEquals(3, p.rev)
        assertEquals(listOf("Voltage_L1", "Energy_Import", "PF"), p.registers.map { it.key })
        assertEquals("Import energy", labelFor(p, "Energy_Import"))
        assertEquals("kWh", unitFor(p, "Energy_Import"))
        assertEquals(listOf("overview", "energy"), viewMap(p).keys.toList())
        assertEquals(listOf("Voltage_L1", "PF"), viewMap(p)["overview"])
    }

    @Test fun registersWithoutLabelOrUnitFallBack() {
        val p = MeterProfile.parse(sdm)!!
        assertEquals("PF", labelFor(p, "PF"))
        assertEquals("", unitFor(p, "PF"))
        assertEquals(2, decimalsFor(p, "PF"))            // unspecified: two digits, as before
        assertEquals(0, decimalsFor(p, "Energy_Import"))
        assertEquals(2, decimalsFor(p, "Voltage_L1"))
    }

    @Test fun decimalsAreCappedAtThree() {
        val p = MeterProfile.parse(JSONObject("""{"registers":[{"key":"A","decimals":6}]}"""))!!
        assertEquals(3, decimalsFor(p, "A"))
    }

    @Test fun noProfileMeansTheDkm440PagesAndNames() {
        assertEquals(VIEWS.keys, viewMap(null).keys)
        assertEquals("Voltage L1", labelFor(null, "MainBus_Voltage_L1"))
        assertEquals("V", unitFor(null, "MainBus_Voltage_L1"))
        assertEquals("Hz", unitFor(null, "MainBus_Freq_L2"))
    }

    @Test fun aProfileWithoutViewsGetsOnePageWithEverything() {
        val p = MeterProfile.parse(JSONObject("""{"registers":[{"key":"A"},{"key":"B"}]}"""))!!
        assertEquals(mapOf("all" to listOf("A", "B")), viewMap(p))
    }

    @Test fun emptyOrUnusablePayloadsParseToNull() {
        assertNull(MeterProfile.parse(JSONObject()))                              // a cleared retained topic
        assertNull(MeterProfile.parse(JSONObject("""{"registers":[]}""")))
        assertNull(MeterProfile.parse(JSONObject("""{"registers":[{"label":"no key"}]}""")))
    }

    @Test fun badViewsAreSkippedNotFatal() {
        val p = MeterProfile.parse(JSONObject(
            """{"registers":[{"key":"A"}],"views":[{"id":"","keys":["A"]},{"id":"ok","keys":["A"]},{"id":"nokeys"}]}"""))!!
        assertEquals(listOf("ok"), p.views.map { it.id })
    }

    // --- through the fleet reducer
    @Test fun profileTopicsReachTheAnalyzerAndClear() {
        var f = Fleet().reduce(Route.AnalyzerProfile("gw-01", "an-01"), sdm)
        assertEquals("sdm630", f.analyzer("gw-01", "an-01")!!.profile!!.id)
        f = f.reduce(Route.AnalyzerProfile("gw-01", "an-01"), JSONObject())     // retained message cleared
        assertNull(f.analyzer("gw-01", "an-01")!!.profile)
    }

    @Test fun listingIsKeptPerModem() {
        val listing = JSONObject("""{"v":2,"profiles":[{"id":"dkm440","rev":1,"n":22,"builtin":true}],"assign":{"an-01":"dkm440"}}""")
        val f = Fleet().reduce(Route.ModemProfiles("gw-01"), listing)
        assertNotNull(f.modems["gw-01"]!!.profiles)
        assertEquals("dkm440", f.modems["gw-01"]!!.profiles!!.getJSONObject("assign").getString("an-01"))
        assertNull(f.reduce(Route.ModemProfiles("gw-01"), JSONObject()).modems["gw-01"]!!.profiles)
    }

    @Test fun telemetryCarriesTheProfileItWasReadWith() {
        val f = Fleet().reduce(
            Route.AnalyzerTelemetry("gw-01", "an-01"),
            JSONObject("""{"v":2,"ts":"t","seq":1,"meter_ok":true,"profile":"sdm630","profile_rev":3,"values":{"Voltage_L1":230.5,"PF":null}}"""),
        )
        val t = f.analyzer("gw-01", "an-01")!!.latest!!
        assertEquals("sdm630", t.profile)
        assertEquals(3, t.profileRev)
        assertTrue(t.values.containsKey("PF") && t.values["PF"] == null)
    }

    @Test fun oldFirmwareTelemetryHasNoProfile() {
        val f = Fleet().reduce(
            Route.AnalyzerTelemetry("gw-01", "an-01"),
            JSONObject("""{"v":2,"ts":"t","seq":1,"meter_ok":true,"values":{"MainBus_Voltage_L1":231.4}}"""),
        )
        assertEquals("", f.analyzer("gw-01", "an-01")!!.latest!!.profile)
    }
}
