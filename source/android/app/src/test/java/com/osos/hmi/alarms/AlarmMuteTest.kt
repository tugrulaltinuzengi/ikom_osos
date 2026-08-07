package com.osos.hmi.alarms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

// Exercises the sleep gate through the notifier seam, so no Android
// NotificationManager is involved.
class AlarmMuteTest {
    private class Recorder : Notifier {
        val sent = mutableListOf<String>()
        val cancelled = mutableListOf<String>()
        override fun post(id: String, title: String, text: String) { sent += id }
        override fun cancel(id: String) { cancelled += id }
    }

    @Test fun awakeAlarmNotifies() {
        val r = Recorder()
        val g = AlarmGate(r)
        g.fire("rule-1", "Voltage L2 low")
        assertEquals(listOf("rule-1"), r.sent)
        assertTrue(g.digest.isEmpty())
    }

    @Test fun mutedAlarmDoesNotNotifyButIsRecorded() {
        val r = Recorder()
        val g = AlarmGate(r)
        g.muted = true
        g.fire("rule-1", "Voltage L2 low")
        assertTrue(r.sent.isEmpty())
        assertEquals(1, g.digest.size)
        assertEquals("Voltage L2 low", g.digest.first().message)
    }

    @Test fun digestAccumulatesAcrossSleep() {
        val r = Recorder()
        val g = AlarmGate(r)
        g.muted = true
        g.fire("rule-1", "a")
        g.fire("rule-2", "b")
        assertEquals(2, g.digest.size)
    }

    @Test fun wakingClearsTheDigestOnceRead() {
        val r = Recorder()
        val g = AlarmGate(r)
        g.muted = true
        g.fire("rule-1", "a")
        g.muted = false
        val taken = g.takeDigest()
        assertEquals(1, taken.size)
        assertTrue(g.digest.isEmpty())
    }

    // Muting must not retroactively silence an already-posted notification.
    @Test fun resolveStillCancelsWhileMuted() {
        val r = Recorder()
        val g = AlarmGate(r)
        g.fire("rule-1", "a")
        g.muted = true
        g.resolve("rule-1")
        assertEquals(listOf("rule-1"), r.cancelled)
    }

    @Test fun duplicateFireIsSuppressed() {
        val r = Recorder()
        val g = AlarmGate(r)
        g.fire("rule-1", "a")
        g.fire("rule-1", "a")
        assertEquals(1, r.sent.size)
        assertFalse(g.active.isEmpty())
    }
}
