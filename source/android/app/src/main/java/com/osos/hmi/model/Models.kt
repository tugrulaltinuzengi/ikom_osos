package com.osos.hmi.model

// Payload shapes mirror tools/fake_gateway.py — the protocol reference.

data class Telemetry(
    val ts: String,
    val seq: Long,
    val buffered: Boolean,
    val meterOk: Boolean,
    val values: Map<String, Double?>,
    val receivedAt: Long,
    /** Meter profile the gateway read this frame with; "" from firmware that predates profiles. */
    val profile: String = "",
    val profileRev: Int = 0,
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


// ---------------------------------------------------------------------------
// Meter profiles (source/meter-profiles/README.md). The gateway publishes, per
// analyzer, the profile it reads with; the app only needs the display half of it.

data class ProfileRegister(
    val key: String,
    val label: String,
    val unit: String,
    val decimals: Int?,
)

data class ProfileView(val id: String, val label: String, val keys: List<String>)

data class MeterProfile(
    val id: String,
    val name: String,
    val rev: Int,
    val registers: List<ProfileRegister>,
    val views: List<ProfileView>,
) {
    fun register(key: String): ProfileRegister? = registers.firstOrNull { it.key == key }

    /** The pages to show. A profile without views gets one page with every register. */
    fun pages(): List<ProfileView> =
        if (views.isNotEmpty()) views
        else listOf(ProfileView("all", "all", registers.map { it.key }))

    companion object {
        /** Null for an empty or unusable payload - which is also how a cleared retained topic arrives. */
        fun parse(j: org.json.JSONObject): MeterProfile? {
            val regs = j.optJSONArray("registers") ?: return null
            val registers = (0 until regs.length()).mapNotNull { i ->
                val o = regs.optJSONObject(i) ?: return@mapNotNull null
                val key = o.optString("key")
                if (key.isEmpty()) return@mapNotNull null
                ProfileRegister(
                    key = key,
                    label = o.optString("label", ""),
                    unit = o.optString("unit", ""),
                    decimals = if (o.has("decimals")) o.optInt("decimals") else null,
                )
            }
            if (registers.isEmpty()) return null
            val vs = j.optJSONArray("views")
            val views = (0 until (vs?.length() ?: 0)).mapNotNull { i ->
                val o = vs!!.optJSONObject(i) ?: return@mapNotNull null
                val ks = o.optJSONArray("keys") ?: return@mapNotNull null
                val id = o.optString("id")
                if (id.isEmpty()) return@mapNotNull null
                ProfileView(id, o.optString("label", id), (0 until ks.length()).map { ks.optString(it) })
            }
            return MeterProfile(j.optString("id"), j.optString("name"), j.optInt("rev", 1), registers, views)
        }
    }
}

/** Tile pages for an analyzer: its profile's, else the DKM-440 pages every build has had. */
fun viewMap(profile: MeterProfile?): Map<String, List<String>> =
    if (profile == null) VIEWS
    else profile.pages().associate { it.id to it.keys }

fun labelFor(profile: MeterProfile?, key: String): String =
    profile?.register(key)?.label?.takeIf { it.isNotEmpty() } ?: shortName(key)

fun unitFor(profile: MeterProfile?, key: String): String =
    profile?.register(key)?.unit ?: unitFor(key)

/** Digits for a tile: the profile's choice, capped at 3, else 2 as before. */
fun decimalsFor(profile: MeterProfile?, key: String): Int =
    (profile?.register(key)?.decimals ?: 2).coerceIn(0, 3)
