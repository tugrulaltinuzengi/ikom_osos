package com.osos.hmi.mqtt

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TopicRouterTest {
    @Test fun buildsModemTopic() =
        assertEquals("osos/m/gw-01/cmd", TopicRouter.modem("gw-01", "cmd"))

    @Test fun buildsAnalyzerTopic() = assertEquals(
        "osos/m/gw-01/a/an-07/telemetry",
        TopicRouter.analyzer("gw-01", "an-07", "telemetry"),
    )

    @Test fun parsesAnalyzerTelemetry() = assertEquals(
        Route.AnalyzerTelemetry("gw-01", "an-07"),
        TopicRouter.parse("osos/m/gw-01/a/an-07/telemetry"),
    )

    @Test fun parsesAnalyzerStatus() = assertEquals(
        Route.AnalyzerStatus("gw-01", "an-07"),
        TopicRouter.parse("osos/m/gw-01/a/an-07/status"),
    )

    @Test fun parsesModemLeaves() {
        assertEquals(Route.ModemStatus("gw-01"), TopicRouter.parse("osos/m/gw-01/status"))
        assertEquals(Route.ModemRegistry("gw-01"), TopicRouter.parse("osos/m/gw-01/registry"))
        assertEquals(Route.ModemState("gw-01"), TopicRouter.parse("osos/m/gw-01/state"))
        assertEquals(Route.ModemAck("gw-01"), TopicRouter.parse("osos/m/gw-01/ack"))
        assertEquals(Route.ModemLabels("gw-01"), TopicRouter.parse("osos/m/gw-01/labels"))
    }

    @Test fun parsesTree() = assertEquals(Route.Tree, TopicRouter.parse("osos/tree"))

    @Test fun parsesLegacyTelemetry() = assertEquals(
        Route.LegacyTelemetry("dkm440-gw1"),
        TopicRouter.parse("osos/dkm440-gw1/telemetry"),
    )

    // The reserved segment is what stops a v2 topic being read as a v1
    // gateway literally named "m".
    @Test fun reservedSegmentIsNotLegacy() =
        assertTrue(TopicRouter.parse("osos/m/telemetry") is Route.Unknown)

    @Test fun rejectsForeignPrefix() =
        assertTrue(TopicRouter.parse("other/m/gw-01/status") is Route.Unknown)

    @Test fun rejectsUnknownLeaf() =
        assertTrue(TopicRouter.parse("osos/m/gw-01/bogus") is Route.Unknown)
}
