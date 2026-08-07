package com.osos.hmi.alarms

import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import com.osos.hmi.data.Prefs
import com.osos.hmi.model.GwStatus
import com.osos.hmi.model.Telemetry
import com.osos.hmi.model.shortName
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

data class AlarmRule(
    val id: String,
    val key: String,
    val min: Double,
    val max: Double,
    val holdSec: Int,
    val enabled: Boolean,
)

data class ActiveAlarm(val id: String, val message: String, val since: Long)

// Phone-side alarming: the DKM-440's Modbus read budget is fixed by the
// report interval (polite master, C-1/C-2), so alarms are evaluated on the
// telemetry stream the gateway already publishes — never by extra polling.
class AlarmEngine(
    private val ctx: Context,
    private val prefs: Prefs,
    private val scope: CoroutineScope,
    private val log: (String, String) -> Unit,
) {
    companion object {
        const val CHANNEL_ID = "alarms"
        private const val METER_FAULT_HOLD_SEC = 30
    }

    val rules = MutableStateFlow(prefs.loadRules())
    val active = MutableStateFlow<List<ActiveAlarm>>(emptyList())

    /** Alarms that fired while asleep, surfaced once on wake. */
    val wakeDigest = MutableStateFlow<List<ActiveAlarm>>(emptyList())

    private val violatedSince = HashMap<String, Long>()
    @Volatile private var lastTelemetryAt = 0L
    @Volatile private var meterFaultSince = 0L
    @Volatile private var gwState: String = "?"

    fun setRules(newRules: List<AlarmRule>) {
        prefs.saveRules(newRules)
        rules.value = newRules
        // rules changed: drop pending state for rules that no longer exist
        val ids = newRules.map { it.id }.toSet()
        violatedSince.keys.retainAll { it in ids }
        gate.retainRules(ids)
        active.value = gate.active
    }

    fun start() {
        scope.launch {
            while (true) {
                delay(5000)
                checkOffline()
            }
        }
    }

    fun onTelemetry(t: Telemetry) {
        lastTelemetryAt = t.receivedAt
        resolve("builtin-offline")

        if (!t.meterOk) {
            if (meterFaultSince == 0L) meterFaultSince = t.receivedAt
            if (t.receivedAt - meterFaultSince >= METER_FAULT_HOLD_SEC * 1000L) {
                fire("builtin-meter", "meter link FAULT for ≥${METER_FAULT_HOLD_SEC}s")
            }
        } else {
            meterFaultSince = 0L
            resolve("builtin-meter")
        }

        val now = t.receivedAt
        for (rule in rules.value) {
            if (!rule.enabled) continue
            val v = t.values[rule.key] ?: continue
            val violated = v < rule.min || v > rule.max
            if (violated) {
                val since = violatedSince.getOrPut(rule.id) { now }
                if (now - since >= rule.holdSec * 1000L) {
                    fire(
                        rule.id,
                        "${shortName(rule.key)} = %.2f outside [%.2f, %.2f] for ≥%ds"
                            .format(v, rule.min, rule.max, rule.holdSec),
                    )
                }
            } else {
                violatedSince.remove(rule.id)
                resolve(rule.id)
            }
        }
    }

    fun onStatus(s: GwStatus) {
        gwState = s.state
        if (s.state == "offline") {
            fire("builtin-offline", "gateway reported offline (LWT)")
        } else if (s.state == "online") {
            resolve("builtin-offline")
        }
    }

    private fun checkOffline() {
        val after = prefs.offlineAfterSec * 1000L
        if (lastTelemetryAt > 0 && System.currentTimeMillis() - lastTelemetryAt > after &&
            gwState != "offline"
        ) {
            fire("builtin-offline", "no telemetry for >${prefs.offlineAfterSec}s")
        }
    }

    private val notifier = object : Notifier {
        override fun post(id: String, title: String, text: String) {
            val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val n: Notification = Notification.Builder(ctx, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_error)
                .setContentTitle(title)
                .setContentText(text)
                .setAutoCancel(true)
                .build()
            try {
                nm.notify(id.hashCode(), n)
            } catch (e: SecurityException) {
                // POST_NOTIFICATIONS not granted — alarm still shows in-app
            }
        }

        override fun cancel(id: String) {
            val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.cancel(id.hashCode())
        }
    }

    private val gate = AlarmGate(notifier)

    /** Driven by the fleet's sleep state, not stored independently. */
    fun setMuted(value: Boolean) {
        val waking = gate.muted && !value
        gate.muted = value
        if (waking) {
            val missed = gate.takeDigest()
            if (missed.isNotEmpty()) {
                log("alarm", "while asleep: ${missed.size} alarm(s)")
                missed.forEach { log("alarm", "  ${it.message}") }
            }
            wakeDigest.value = missed
        }
    }

    private fun fire(id: String, message: String) {
        if (gate.fire(id, message)) {
            active.value = gate.active
            log("alarm", if (gate.muted) "ALARM (muted): $message" else "ALARM: $message")
        }
    }

    private fun resolve(id: String) {
        val was = gate.resolve(id) ?: return
        active.value = gate.active
        log("alarm", "resolved: ${was.message}")
    }
}
