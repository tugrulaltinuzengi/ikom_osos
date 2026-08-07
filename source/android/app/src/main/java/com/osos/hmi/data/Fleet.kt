package com.osos.hmi.data

import com.osos.hmi.model.GwStatus
import com.osos.hmi.model.ModemState
import com.osos.hmi.model.Telemetry
import com.osos.hmi.mqtt.Protocol
import com.osos.hmi.mqtt.Route
import org.json.JSONObject

data class AnalyzerEntry(
    val mid: String,
    val aid: String,
    val name: String,
    val folder: String,
    val host: String = "",
    val unit: Int = 0,
    val interval: Int = 0,
    val latest: Telemetry? = null,
    val link: String = "?",
    /** True if the modem's registry listed it. Telemetry-discovered analyzers
     *  are not in any registry and must survive a registry update. */
    val fromRegistry: Boolean = false,
)

data class ModemEntry(
    val mid: String,
    val status: GwStatus? = null,
    val state: ModemState? = null,
    val analyzers: Map<String, AnalyzerEntry> = emptyMap(),
    val protocolVersion: Int = Protocol.VERSION,
    val unsupportedVersion: Boolean = false,
    val loadChannels: Int = 0,
)

/**
 * Immutable fleet state plus a pure reducer. No Android, no I/O, no coroutines
 * - which is what makes every rule below testable on the JVM.
 *
 * Registry and labels are separate topics with separate owners (spec D-2), and
 * MQTT does not guarantee retained delivery order, so the merge has to work in
 * either arrival order. Labels are therefore kept even when they refer to an
 * analyzer the registry has not yet introduced.
 */
data class Fleet(
    val modems: Map<String, ModemEntry> = emptyMap(),
    private val pendingLabels: Map<String, Map<String, Pair<String, String>>> = emptyMap(),
) {
    companion object {
        /** Synthetic analyzer ID for a legacy v1 gateway's single meter. */
        const val LEGACY_AID = "an-0"
    }

    fun analyzer(mid: String, aid: String): AnalyzerEntry? =
        modems[mid]?.analyzers?.get(aid)

    val allAnalyzers: List<AnalyzerEntry>
        get() = modems.values.flatMap { it.analyzers.values }

    fun reduce(route: Route, json: JSONObject): Fleet = when (route) {
        is Route.ModemStatus -> upsert(route.mid) {
            it.copy(
                status = GwStatus(
                    json.optString("state", "?"), json.optString("fw", ""),
                    json.optString("bearer", ""), json.optString("ip", ""),
                    json.optInt("rssi", 0),
                ),
                unsupportedVersion = json.optInt("v", Protocol.VERSION) > Protocol.VERSION,
            )
        }

        is Route.ModemState -> upsert(route.mid) {
            val loads = json.optJSONArray("loads")
            it.copy(
                state = ModemState(
                    sleep = json.optBoolean("sleep", false),
                    interval = json.optInt("interval", 0),
                    loads = (0 until (loads?.length() ?: 0)).map { i -> loads!!.optBoolean(i) },
                    since = json.optString("since", ""),
                )
            )
        }

        is Route.ModemRegistry -> reduceRegistry(route.mid, json)
        is Route.ModemLabels -> reduceLabels(route.mid, json)
        is Route.AnalyzerTelemetry -> upsertAnalyzer(route.mid, route.aid) {
            it.copy(latest = parseTelemetry(json))
        }
        is Route.AnalyzerStatus -> upsertAnalyzer(route.mid, route.aid) {
            it.copy(link = json.optString("state", "?"))
        }
        is Route.LegacyTelemetry -> upsert(route.gwId) { it.copy(protocolVersion = 1) }
            .upsertAnalyzer(route.gwId, LEGACY_AID) { it.copy(latest = parseTelemetry(json)) }
        is Route.LegacyStatus -> upsert(route.gwId) {
            it.copy(
                protocolVersion = 1,
                status = GwStatus(
                    json.optString("state", "?"), json.optString("fw", ""),
                    json.optString("bearer", ""), json.optString("ip", ""),
                    json.optInt("rssi", 0),
                ),
            )
        }
        else -> this
    }

    private fun reduceRegistry(mid: String, json: JSONObject): Fleet {
        val arr = json.optJSONArray("analyzers") ?: return this
        val labels = pendingLabels[mid].orEmpty()
        var next = upsert(mid) {
            it.copy(loadChannels = json.optJSONObject("loads")?.optInt("channels", 0) ?: 0)
        }
        val listed = mutableSetOf<String>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            // `continue` cannot be used inside an ifEmpty {} lambda - it is
            // loop control, not a lambda return.
            val aid = o.optString("id")
            if (aid.isEmpty()) continue
            listed += aid
            val label = labels[aid]
            next = next.upsertAnalyzer(mid, aid) {
                it.copy(
                    host = o.optString("host", ""),
                    unit = o.optInt("unit", 0),
                    interval = o.optInt("interval", 0),
                    name = label?.first ?: it.name,
                    folder = label?.second ?: it.folder,
                    fromRegistry = true,
                )
            }
        }

        // The registry is authoritative for the analyzers it introduced, so one
        // that has dropped out of it is gone and must not linger showing "—".
        // Telemetry-discovered analyzers were never in a registry and stay.
        return next.upsert(mid) { m ->
            m.copy(analyzers = m.analyzers.filterValues { !it.fromRegistry || it.aid in listed })
        }
    }

    private fun reduceLabels(mid: String, json: JSONObject): Fleet {
        val obj = json.optJSONObject("labels") ?: return this
        val parsed = obj.keys().asSequence().associateWith { aid ->
            val o = obj.optJSONObject(aid)
            (o?.optString("name")?.ifEmpty { aid } ?: aid) to (o?.optString("folder") ?: "")
        }
        var next = copy(pendingLabels = pendingLabels + (mid to parsed))
        for ((aid, label) in parsed) {
            if (next.analyzer(mid, aid) == null) continue
            next = next.upsertAnalyzer(mid, aid) {
                it.copy(name = label.first, folder = label.second)
            }
        }
        return next
    }

    private fun upsert(mid: String, f: (ModemEntry) -> ModemEntry): Fleet {
        val cur = modems[mid] ?: ModemEntry(mid)
        return copy(modems = modems + (mid to f(cur)))
    }

    private fun upsertAnalyzer(
        mid: String,
        aid: String,
        f: (AnalyzerEntry) -> AnalyzerEntry,
    ): Fleet = upsert(mid) { m ->
        val cur = m.analyzers[aid] ?: AnalyzerEntry(mid, aid, name = aid, folder = "")
        m.copy(analyzers = m.analyzers + (aid to f(cur)))
    }

    private fun parseTelemetry(j: JSONObject): Telemetry {
        val values = LinkedHashMap<String, Double?>()
        j.optJSONObject("values")?.let { jv ->
            for (key in jv.keys()) values[key] = if (jv.isNull(key)) null else jv.optDouble(key)
        }
        return Telemetry(
            ts = j.optString("ts", ""),
            seq = j.optLong("seq", 0),
            buffered = j.optBoolean("buffered", false),
            meterOk = j.optBoolean("meter_ok", false),
            values = values,
            receivedAt = System.currentTimeMillis(),
        )
    }
}
