package com.osos.hmi.mqtt

/**
 * Owns every MQTT topic filter the app should hold at a given moment.
 *
 * Retained fleet identity/state topics stay always-on. High-rate telemetry is
 * attached only to the open modems. Per-analyzer status is still global because
 * today's firmware has no modem-level health summary; flip
 * [globalAnalyzerStatus] when that exists.
 *
 * A set rather than one id: the analyzer the app is acting on (Draw / Cmds /
 * Alarms / Console all target it) and the modem the Monitor happens to be
 * showing are two different things, and both need their telemetry.
 */
data class SubscriptionPolicy(
    val openModems: Set<String> = emptySet(),
    val globalAnalyzerStatus: Boolean = true,
    val includeLegacyV1: Boolean = true,
) {
    fun filters(): Set<String> = buildSet {
        addAll(ALWAYS_ON)
        if (globalAnalyzerStatus) add(TopicRouter.allAnalyzerStatus())
        openModems.forEach { mid ->
            add(TopicRouter.modemAnalyzers(mid, "telemetry"))
            if (!globalAnalyzerStatus) add(TopicRouter.modemAnalyzers(mid, "status"))
        }
        if (includeLegacyV1) addAll(LEGACY_V1)
    }

    companion object {
        val ALWAYS_ON = setOf(
            TopicRouter.allModems("status"),
            TopicRouter.allModems("registry"),
            TopicRouter.allModems("state"),
            TopicRouter.allModems("ack"),
            TopicRouter.allModems("labels"),
            TopicRouter.TREE,
        )

        val LEGACY_V1 = setOf(
            TopicRouter.legacy("telemetry"),
            TopicRouter.legacy("status"),
        )
    }
}
