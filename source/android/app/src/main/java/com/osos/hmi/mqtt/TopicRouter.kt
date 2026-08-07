package com.osos.hmi.mqtt

/** Protocol version carried by every modem-published payload.
 *  Counterparts: tools/osos_proto.py PROTO_V, firmware kProtocolVersion. */
object Protocol {
    const val VERSION = 2
}

/** A parsed topic. Every subscription callback dispatches on one of these. */
sealed interface Route {
    data class ModemStatus(val mid: String) : Route
    data class ModemRegistry(val mid: String) : Route
    data class ModemState(val mid: String) : Route
    data class ModemEvent(val mid: String) : Route
    data class ModemAck(val mid: String) : Route
    data class ModemLabels(val mid: String) : Route
    data class AnalyzerTelemetry(val mid: String, val aid: String) : Route
    data class AnalyzerStatus(val mid: String, val aid: String) : Route
    data object Tree : Route

    /** Pre-v2 single-gateway topics. No "v" field, therefore v1 by definition. */
    data class LegacyTelemetry(val gwId: String) : Route
    data class LegacyStatus(val gwId: String) : Route

    data class Unknown(val topic: String) : Route
}

// The ONLY place topic segment order exists on the Kotlin side. Everything
// else - GatewayClient, Fleet, TreeStore - goes through here.
object TopicRouter {
    private const val ROOT = "osos"
    private const val MODEM = "m"
    private const val ANALYZER = "a"

    const val TREE = "$ROOT/tree"

    // Kept for older call sites/tests. Runtime subscriptions are now computed
    // by SubscriptionPolicy so telemetry can follow the open modem.
    val SUBSCRIPTIONS = listOf(
        "$ROOT/$MODEM/+/status",
        "$ROOT/$MODEM/+/registry",
        "$ROOT/$MODEM/+/state",
        "$ROOT/$MODEM/+/ack",
        "$ROOT/$MODEM/+/labels",
        "$ROOT/$MODEM/+/$ANALYZER/+/status",
        TREE,
        "$ROOT/+/telemetry",
        "$ROOT/+/status",
    )

    fun modem(mid: String, leaf: String) = "$ROOT/$MODEM/$mid/$leaf"
    fun allModems(leaf: String) = "$ROOT/$MODEM/+/$leaf"
    fun modemAnalyzers(mid: String, leaf: String) = "$ROOT/$MODEM/$mid/$ANALYZER/+/$leaf"
    fun allAnalyzerStatus() = "$ROOT/$MODEM/+/$ANALYZER/+/status"
    fun legacy(leaf: String) = "$ROOT/+/$leaf"
    fun analyzer(mid: String, aid: String, leaf: String) =
        "$ROOT/$MODEM/$mid/$ANALYZER/$aid/$leaf"

    fun parse(topic: String): Route {
        val s = topic.split("/")
        if (s.firstOrNull() != ROOT) return Route.Unknown(topic)

        if (s.size == 2 && s[1] == "tree") return Route.Tree

        if (s.size == 4 && s[1] == MODEM) return when (s[3]) {
            "status" -> Route.ModemStatus(s[2])
            "registry" -> Route.ModemRegistry(s[2])
            "state" -> Route.ModemState(s[2])
            "event" -> Route.ModemEvent(s[2])
            "ack" -> Route.ModemAck(s[2])
            "labels" -> Route.ModemLabels(s[2])
            else -> Route.Unknown(topic)
        }

        if (s.size == 6 && s[1] == MODEM && s[3] == ANALYZER) return when (s[5]) {
            "telemetry" -> Route.AnalyzerTelemetry(s[2], s[4])
            "status" -> Route.AnalyzerStatus(s[2], s[4])
            else -> Route.Unknown(topic)
        }

        // Legacy. Excluding the reserved segment is what stops
        // osos/m/telemetry being read as a gateway named "m".
        if (s.size == 3 && s[1] != MODEM) return when (s[2]) {
            "telemetry" -> Route.LegacyTelemetry(s[1])
            "status" -> Route.LegacyStatus(s[1])
            else -> Route.Unknown(topic)
        }

        return Route.Unknown(topic)
    }
}
