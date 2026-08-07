package com.osos.hmi.model

/**
 * Where the Monitor tab is: fleet tree -> modem -> analyzer. Done this way
 * rather than as new tabs because a seventh tab wraps its label at ~57 dp -
 * the problem AppRoot already documents having fixed once.
 *
 * Lives in the model, not in MonitorScreen, because AppContainer derives the
 * MQTT subscription policy from it. Held in a Composable it would reset - and
 * unsubscribe telemetry - every time the user looked at another tab.
 */
sealed interface MonitorLevel {
    data object Tree : MonitorLevel
    data class Modem(val mid: String) : MonitorLevel
    data class Analyzer(val who: AnalyzerKey) : MonitorLevel
}
