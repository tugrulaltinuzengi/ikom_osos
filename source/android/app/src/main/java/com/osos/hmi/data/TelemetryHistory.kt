package com.osos.hmi.data

import com.osos.hmi.model.AnalyzerKey
import com.osos.hmi.model.Telemetry
import kotlinx.coroutines.flow.MutableStateFlow

// Bounded in-memory telemetry history: powers sparklines and hold-time alarm
// evaluation. ~2 h at the default 10 s interval; deliberately not a database
// ("mediocre monitoring" scope — the meter isn't that complicated).
//
// The cap is per analyzer, not across the fleet: with 75 analyzers a shared
// ring would hold ~9 frames each and every sparkline would be empty.
class TelemetryHistory(private val cap: Int = 720) {

    private val frames = HashMap<AnalyzerKey, ArrayDeque<Pair<Long, Map<String, Double?>>>>()
    val version = MutableStateFlow(0)

    @Synchronized
    fun add(who: AnalyzerKey, t: Telemetry) {
        val ring = frames.getOrPut(who) { ArrayDeque() }
        ring.addLast(t.receivedAt to t.values)
        while (ring.size > cap) ring.removeFirst()
        version.value = version.value + 1
    }

    @Synchronized
    fun series(who: AnalyzerKey, key: String): List<Pair<Long, Double>> =
        frames[who].orEmpty().mapNotNull { (ts, v) -> v[key]?.let { ts to it } }

    @Synchronized
    fun size(who: AnalyzerKey): Int = frames[who]?.size ?: 0
}
