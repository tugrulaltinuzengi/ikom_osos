package com.osos.hmi

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import com.osos.hmi.alarms.AlarmEngine
import com.osos.hmi.console.ConsoleInterpreter
import com.osos.hmi.data.CustomCommandStore
import com.osos.hmi.data.Fleet
import com.osos.hmi.data.Prefs
import com.osos.hmi.data.TelemetryHistory
import com.osos.hmi.data.TreeStore
import com.osos.hmi.model.AnalyzerKey
import com.osos.hmi.model.DigitCommand
import com.osos.hmi.model.GwStatus
import com.osos.hmi.model.LogEntry
import com.osos.hmi.model.MonitorLevel
import com.osos.hmi.model.Telemetry
import com.osos.hmi.mqtt.GatewayClient
import com.osos.hmi.mqtt.Route
import com.osos.hmi.mqtt.TopicRouter
import com.osos.hmi.mqtt.SubscriptionPolicy
import com.osos.hmi.nn.Mlp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import org.json.JSONObject

class OsosApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(
                AlarmEngine.CHANNEL_ID, "Meter alarms",
                NotificationManager.IMPORTANCE_HIGH,
            )
        )
        container = AppContainer(this)
    }
}

class AppContainer(app: Application) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val logEntries = MutableStateFlow<List<LogEntry>>(emptyList())
    fun log(source: String, text: String) {
        logEntries.value =
            (logEntries.value + LogEntry(System.currentTimeMillis(), source, text)).takeLast(100)
    }

    val prefs = Prefs(app)
    val mlp: Mlp = Mlp.loadFromAssets(app)
    private val assetDigits: Map<Int, DigitCommand> = loadDigitMap(app)
    // live map (asset + saved console binds) — the recognizer reads it per draw
    val digitMap = MutableStateFlow(assetDigits + prefs.loadDigitBinds())
    val history = TelemetryHistory()
    val store = CustomCommandStore(app, mlp, scope)
    val client = GatewayClient(scope, ::log)
    val alarms = AlarmEngine(app, prefs, scope, ::log)
    val recognizer = Recognizer(mlp, store, prefs, digitMap)

    val fleet = MutableStateFlow(Fleet())
    val tree = TreeStore(client, clientId = "phone-${System.currentTimeMillis().toString(36)}")

    /** Which analyzer the Draw / Cmds / Alarms tabs act on. */
    val selected = MutableStateFlow<AnalyzerKey?>(null)

    /** Modem owning the selected analyzer — the target for its commands. */
    fun selectedMid(): String? = selected.value?.mid

    /** Modem the Monitor currently has open, if any. */
    val openModem = MutableStateFlow<String?>(null)

    /** Where the Monitor is. Here rather than in the Composable so that
     *  looking at another tab neither forgets the place nor — because the
     *  subscription policy is derived from it — drops telemetry. */
    val monitorLevel = MutableStateFlow<MonitorLevel>(MonitorLevel.Tree)

    fun openMonitorModem(mid: String) {
        openModem.value = mid
        monitorLevel.value = MonitorLevel.Modem(mid)
    }

    fun openMonitorAnalyzer(who: AnalyzerKey) {
        selected.value = who
        openModem.value = who.mid
        monitorLevel.value = MonitorLevel.Analyzer(who)
    }

    /** Back to the fleet tree. The selected analyzer keeps its telemetry —
     *  the tabs that act on it are still pointed at it. */
    fun closeMonitorDetail() {
        openModem.value = null
        monitorLevel.value = MonitorLevel.Tree
    }

    fun selectedStatus(): GwStatus? =
        selected.value?.let { fleet.value.modems[it.mid]?.status }

    fun selectedTelemetry(): Telemetry? =
        selected.value?.let { fleet.value.analyzer(it.mid, it.aid)?.latest }

    // cross-screen UI state (draw pad "view" commands switch the monitor tab)
    val uiTab = MutableStateFlow(0)
    val uiMonitorView = MutableStateFlow("overview")

    /** A drawn or typed "view" action: point the Monitor at [page] on the
     *  selected analyzer — the only level that renders a page. Switching to
     *  the tab is left to the caller, because the draw pad holds it back
     *  500 ms so the recognition result stays readable. */
    fun showMonitorView(page: String) {
        uiMonitorView.value = page
        selected.value?.let { openMonitorAnalyzer(it) }
    }

    // console scrollback lives here so it survives tab switches
    val consoleLines = MutableStateFlow(listOf(ConsoleInterpreter.BANNER))

    // Console `bind`: persist only the deltas against commands.json, so a
    // later asset update still wins for digits the user never touched.
    fun setDigitBinds(map: Map<Int, DigitCommand>) {
        prefs.saveDigitBinds(map.filterValues { assetDigits[it.digit] != it })
        digitMap.value = map
    }

    fun resetDigitBinds() = setDigitBinds(assetDigits)

    init {
        store.load()
        alarms.start()
        scope.launch {
            client.messages.collect { (topic, json) ->
                val route = TopicRouter.parse(topic)
                if (route is Route.Tree) { tree.applyTree(json); return@collect }
                val next = fleet.value.reduce(route, json)
                fleet.value = next

                if (route is Route.AnalyzerTelemetry) {
                    val who = AnalyzerKey(route.mid, route.aid)
                    next.analyzer(route.mid, route.aid)?.latest?.let {
                        history.add(who, it)
                        if (selected.value == null) selected.value = who
                        if (selected.value == who) alarms.onTelemetry(it)
                    }
                }
                if (route is Route.LegacyTelemetry) {
                    val who = AnalyzerKey(route.gwId, Fleet.LEGACY_AID)
                    next.analyzer(route.gwId, Fleet.LEGACY_AID)?.latest?.let {
                        history.add(who, it)
                        if (selected.value == null) selected.value = who
                    }
                }
                if (route is Route.ModemState) {
                    // Sleep is authoritative from the fleet, never a local guess.
                    val anyAsleep = next.modems.values.any { it.state?.sleep == true }
                    alarms.setMuted(anyAsleep)
                }
                if (route is Route.ModemStatus) {
                    next.modems[route.mid]?.status?.let { alarms.onStatus(it) }
                }
            }
        }
        // Telemetry follows app state, never composition. The selected analyzer
        // is what Alarms / Draw / Cmds / Console act on, so its modem stays
        // subscribed no matter which tab is on screen; the Monitor's open modem
        // rides along so its tree rows show live values.
        scope.launch {
            combine(selected, openModem) { sel, open -> setOfNotNull(sel?.mid, open) }
                .distinctUntilChanged()
                .collect { client.setSubscriptionPolicy(SubscriptionPolicy(openModems = it)) }
        }

        log("app", "net ${mlp.archLabel} loaded, ${digitMap.value.size} digit commands")
        client.connect(prefs.brokerConfig())
    }

    // config/commands.json (bundled asset): { "digits": { "0": {scope, action, args, label} } }
    private fun loadDigitMap(app: Application): Map<Int, DigitCommand> {
        val doc = JSONObject(app.assets.open("commands.json").readBytes().decodeToString())
        val digits = doc.getJSONObject("digits")
        val map = LinkedHashMap<Int, DigitCommand>()
        for (key in digits.keys()) {
            val d = key.toIntOrNull() ?: continue
            val o = digits.getJSONObject(key)
            val args = o.optJSONObject("args")
            map[d] = DigitCommand(
                digit = d,
                scope = o.optString("scope", "none"),
                action = o.optString("action", ""),
                seconds = args?.optInt("seconds", 0) ?: 0,
                page = args?.optString("page", "") ?: "",
                label = o.optString("label", ""),
            )
        }
        return map
    }
}
