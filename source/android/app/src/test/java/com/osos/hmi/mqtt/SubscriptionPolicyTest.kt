package com.osos.hmi.mqtt

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

// High-rate analyzer telemetry is the one thing that follows app state rather
// than being always-on, so these tests pin exactly which filters that adds and
// removes. A regression here is invisible in the UI until an alarm is missed.
class SubscriptionPolicyTest {

    private fun telemetryFilters(p: SubscriptionPolicy) =
        p.filters().filter { it.endsWith("/a/+/telemetry") }.toSet()

    @Test fun noOpenModemHoldsNoAnalyzerTelemetry() =
        assertTrue(telemetryFilters(SubscriptionPolicy()).isEmpty())

    @Test fun oneOpenModemAddsExactlyItsTelemetry() = assertEquals(
        setOf("osos/m/gw-01/a/+/telemetry"),
        telemetryFilters(SubscriptionPolicy(openModems = setOf("gw-01"))),
    )

    @Test fun twoOpenModemsAddBoth() = assertEquals(
        setOf("osos/m/gw-01/a/+/telemetry", "osos/m/gw-02/a/+/telemetry"),
        telemetryFilters(SubscriptionPolicy(openModems = setOf("gw-01", "gw-02"))),
    )

    // Identity, state, acks and legacy v1 must never depend on navigation:
    // dropping them would silence the gateway-offline alarm and the ack banner.
    @Test fun everythingElseIsIndependentOfTheOpenModems() {
        val closed = SubscriptionPolicy().filters() - telemetryFilters(SubscriptionPolicy())
        val open = SubscriptionPolicy(openModems = setOf("gw-01", "gw-02")).let {
            it.filters() - telemetryFilters(it)
        }
        assertEquals(closed, open)
        assertTrue("osos/m/+/ack" in closed)
        assertTrue("osos/m/+/a/+/status" in closed)
        assertTrue("osos/+/telemetry" in closed)
    }
}
