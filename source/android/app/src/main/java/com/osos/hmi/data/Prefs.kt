package com.osos.hmi.data

import android.content.Context
import com.osos.hmi.alarms.AlarmRule
import com.osos.hmi.model.DigitCommand
import com.osos.hmi.mqtt.BrokerConfig
import org.json.JSONArray
import org.json.JSONObject

// Broker/gateway settings + recognition thresholds + alarm rules.
// Defaults mirror www/config.example.js (playground broker, anonymous).
class Prefs(ctx: Context) {
    private val sp = ctx.getSharedPreferences("osos", Context.MODE_PRIVATE)

    var host: String
        get() = sp.getString("host", "broker.emqx.io")!!
        set(v) = sp.edit().putString("host", v).apply()
    var port: Int
        get() = sp.getInt("port", 1883)
        set(v) = sp.edit().putInt("port", v).apply()
    var tls: Boolean
        get() = sp.getBoolean("tls", false)
        set(v) = sp.edit().putBoolean("tls", v).apply()
    var user: String
        get() = sp.getString("user", "")!!
        set(v) = sp.edit().putString("user", v).apply()
    var pass: String
        get() = sp.getString("pass", "")!!
        set(v) = sp.edit().putString("pass", v).apply()
    // No gwId here. In the browser HMI it was the v1 gateway id that built
    // osos/{gwId}/telemetry; v2 addresses modems by wildcard and TopicRouter
    // owns the root, so nothing could read it. A configurable root would mean
    // making TopicRouter an instance — a real change, not a settings field.

    // hmi.js defaults: confMin 0.90 (digits), simMin 0.93 (cosine match);
    // headMin gates the on-device trained head.
    var confMin: Float
        get() = sp.getFloat("confMin", 0.90f)
        set(v) = sp.edit().putFloat("confMin", v).apply()
    var simMin: Float
        get() = sp.getFloat("simMin", 0.93f)
        set(v) = sp.edit().putFloat("simMin", v).apply()
    var headMin: Float
        get() = sp.getFloat("headMin", 0.85f)
        set(v) = sp.edit().putFloat("headMin", v).apply()

    var offlineAfterSec: Int
        get() = sp.getInt("offlineAfterSec", 60)
        set(v) = sp.edit().putInt("offlineAfterSec", v).apply()

    fun brokerConfig() = BrokerConfig(host, port, tls, user, pass)

    fun loadRules(): List<AlarmRule> {
        val raw = sp.getString("alarmRules", null) ?: return emptyList()
        return try {
            val arr = JSONArray(raw)
            (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                AlarmRule(
                    id = o.getString("id"),
                    key = o.getString("key"),
                    min = o.getDouble("min"),
                    max = o.getDouble("max"),
                    holdSec = o.getInt("holdSec"),
                    enabled = o.getBoolean("enabled"),
                )
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    fun saveRules(rules: List<AlarmRule>) {
        val arr = JSONArray()
        rules.forEach { r ->
            arr.put(
                JSONObject()
                    .put("id", r.id).put("key", r.key)
                    .put("min", r.min).put("max", r.max)
                    .put("holdSec", r.holdSec).put("enabled", r.enabled)
            )
        }
        sp.edit().putString("alarmRules", arr.toString()).apply()
    }

    // Console `bind` overrides. Only the digits that differ from commands.json
    // are stored, so the asset stays the seed for everything untouched.
    fun loadDigitBinds(): Map<Int, DigitCommand> {
        val raw = sp.getString("digitBinds", null) ?: return emptyMap()
        return try {
            val arr = JSONArray(raw)
            (0 until arr.length()).associate { i ->
                val o = arr.getJSONObject(i)
                val d = o.getInt("digit")
                d to DigitCommand(
                    digit = d,
                    scope = o.getString("scope"),
                    action = o.getString("action"),
                    seconds = o.getInt("seconds"),
                    page = o.getString("page"),
                    label = o.getString("label"),
                )
            }
        } catch (e: Exception) {
            emptyMap()
        }
    }

    fun saveDigitBinds(binds: Map<Int, DigitCommand>) {
        val arr = JSONArray()
        binds.values.sortedBy { it.digit }.forEach { d ->
            arr.put(
                JSONObject()
                    .put("digit", d.digit).put("scope", d.scope)
                    .put("action", d.action).put("seconds", d.seconds)
                    .put("page", d.page).put("label", d.label)
            )
        }
        sp.edit().putString("digitBinds", arr.toString()).apply()
    }
}
