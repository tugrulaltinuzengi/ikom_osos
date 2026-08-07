package com.osos.hmi.model

// Payload shapes mirror tools/fake_gateway.py — the protocol reference.

data class Telemetry(
    val ts: String,
    val seq: Long,
    val buffered: Boolean,
    val meterOk: Boolean,
    val values: Map<String, Double?>,
    val receivedAt: Long,
)

data class GwStatus(
    val state: String,
    val fw: String,
    val bearer: String,
    val ip: String,
    val rssi: Int,
)

data class Ack(val id: String, val ok: Boolean, val detail: String)

data class ModemState(
    val sleep: Boolean,
    val interval: Int,
    val loads: List<Boolean>,
    val since: String,
)

/** Identifies one analyzer across the whole fleet. */
data class AnalyzerKey(val mid: String, val aid: String)

data class LogEntry(val time: Long, val source: String, val text: String)

// One digit slot of config/commands.json (bundled as an asset).
data class DigitCommand(
    val digit: Int,
    val scope: String,   // "gateway" | "local" | "none"
    val action: String,
    val seconds: Int,    // set_interval only
    val page: String,    // local view only
    val label: String,
)

// Actions a custom symbol can be bound to (mirrors www/hmi.js ACTIONS).
data class BoundAction(
    val key: String,
    val label: String,
    val scope: String,          // "gateway" | "local"
    val action: String = "",
    val seconds: Int = 0,
    val page: String = "",
)

val BOUND_ACTIONS = listOf(
    BoundAction("read_now", "read now", "gateway", action = "read_now"),
    BoundAction("ping", "ping gateway", "gateway", action = "ping"),
    BoundAction("int2", "fast reporting (2 s)", "gateway", action = "set_interval", seconds = 2),
    BoundAction("int10", "normal reporting (10 s)", "gateway", action = "set_interval", seconds = 10),
    BoundAction("viewL1", "show L1", "local", page = "L1"),
    BoundAction("viewL2", "show L2", "local", page = "L2"),
    BoundAction("viewL3", "show L3", "local", page = "L3"),
    BoundAction("viewOvw", "overview", "local", page = "overview"),
    BoundAction("viewPow", "power view", "local", page = "power"),
)

private fun phaseKeys(ph: String) = listOf(
    "MainBus_Voltage_$ph", "MainBus_Current_$ph", "MainBus_Freq_$ph",
    "MainBus_PF_$ph", "MainBus_CosPhi_$ph", "MainBus_TanPhi_$ph",
)

// The five tile views of www/hmi.js, key lists verbatim.
val VIEWS: LinkedHashMap<String, List<String>> = linkedMapOf(
    "overview" to listOf(
        "MainBus_Voltage_L1", "MainBus_Voltage_L2", "MainBus_Voltage_L3",
        "MainBus_Current_L1", "MainBus_Current_L2", "MainBus_Current_L3",
        "MainBus_Freq_L1", "Supply_Voltage",
        "MainBus_Voltage_N", "MainBus_Current_N",
    ),
    "L1" to phaseKeys("L1"),
    "L2" to phaseKeys("L2"),
    "L3" to phaseKeys("L3"),
    "power" to listOf(
        "MainBus_PF_L1", "MainBus_PF_L2", "MainBus_PF_L3",
        "MainBus_CosPhi_L1", "MainBus_CosPhi_L2", "MainBus_CosPhi_L3",
        "MainBus_TanPhi_Tot",
        "MainBus_TanPhi_L1", "MainBus_TanPhi_L2", "MainBus_TanPhi_L3",
    ),
)

val ALL_KEYS: List<String> = VIEWS.values.flatten().distinct()

fun shortName(key: String): String = key.removePrefix("MainBus_").replace('_', ' ')

fun unitFor(key: String): String = when {
    key.contains("Voltage") -> "V"
    key.contains("Current") -> "A"
    key.contains("Freq") -> "Hz"
    else -> ""
}
