package com.osos.hmi.alarms

/** Seam over the platform notifier, so the sleep gate is JVM-testable. */
interface Notifier {
    fun post(id: String, title: String, text: String)
    fun cancel(id: String)
}

/**
 * Fire/resolve bookkeeping plus the sleep gate.
 *
 * Sleep mutes the notification and nothing else (spec D-3): the alarm still
 * enters the active list and the digest, so "was there a fault at 03:00" stays
 * answerable after a night asleep.
 */
class AlarmGate(private val notifier: Notifier) {
    var muted: Boolean = false

    private val _active = mutableListOf<ActiveAlarm>()
    val active: List<ActiveAlarm> get() = _active.toList()

    private val _digest = mutableListOf<ActiveAlarm>()
    val digest: List<ActiveAlarm> get() = _digest.toList()

    fun fire(id: String, message: String): Boolean {
        if (_active.any { it.id == id }) return false
        val alarm = ActiveAlarm(id, message, System.currentTimeMillis())
        _active += alarm
        if (muted) _digest += alarm else notifier.post(id, "OSOS alarm", message)
        return true
    }

    fun resolve(id: String): ActiveAlarm? {
        val was = _active.find { it.id == id } ?: return null
        _active.removeAll { it.id == id }
        // Always cancel: an alarm posted before sleep began must still clear.
        notifier.cancel(id)
        return was
    }

    fun retainRules(ids: Set<String>) {
        _active.removeAll { it.id !in ids && !it.id.startsWith("builtin") }
    }

    fun takeDigest(): List<ActiveAlarm> {
        val out = _digest.toList()
        _digest.clear()
        return out
    }
}
