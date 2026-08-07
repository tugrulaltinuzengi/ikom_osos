package com.osos.hmi.mqtt

import com.hivemq.client.mqtt.datatypes.MqttQos
import com.hivemq.client.mqtt.mqtt3.Mqtt3AsyncClient
import com.hivemq.client.mqtt.mqtt3.Mqtt3Client
import com.osos.hmi.model.Ack
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.random.Random

data class BrokerConfig(
    val host: String,
    val port: Int,
    val tls: Boolean,
    val user: String,
    val pass: String,
)

// Transport only. This class knows how to connect, subscribe, publish and
// match acks - it knows nothing about topic structure. Parsing is TopicRouter's
// job and interpretation is Fleet's, so a schema change touches neither.
class GatewayClient(
    private val scope: CoroutineScope,
    private val log: (String, String) -> Unit,
) {
    val connected = MutableStateFlow(false)
    val lastAck = MutableStateFlow<Ack?>(null)
    val cmdBanner = MutableStateFlow<String?>(null)

    /** Raw (topic, payload) pairs. Routing is the Fleet's job, not this class's. */
    val messages = MutableSharedFlow<Pair<String, JSONObject>>(extraBufferCapacity = 256)

    /** The filters actually held right now — telemetry follows the open modems,
     *  so this is the honest answer to "why is that tile empty?". */
    val activeFilters = MutableStateFlow<Set<String>>(emptySet())

    private var client: Mqtt3AsyncClient? = null
    private val pendingAcks = ConcurrentHashMap<String, Job>()

    // Reconciliation is reached from two threads: the Compose main thread on
    // every navigation, and HiveMQ's callback thread on connect/disconnect.
    private val subLock = Any()
    @Volatile private var desiredPolicy = SubscriptionPolicy()
    /** Guarded by [subLock]. */
    private val activeSubscriptions = linkedSetOf<String>()

    fun connect(config: BrokerConfig) {
        disconnect()
        val clientId = "phone-" + List(8) { "0123456789abcdef"[Random.nextInt(16)] }.joinToString("")
        var builder = Mqtt3Client.builder()
            .identifier(clientId)
            .serverHost(config.host)
            .serverPort(config.port)
            .automaticReconnect()
            .initialDelay(1, TimeUnit.SECONDS)
            .maxDelay(30, TimeUnit.SECONDS)
            .applyAutomaticReconnect()
            .addConnectedListener { onConnected() }
            .addDisconnectedListener {
                if (connected.value) log("broker", "disconnected")
                connected.value = false
                forgetActiveSubscriptions()
            }
        if (config.tls) builder = builder.sslWithDefaultConfig()
        val c = builder.buildAsync()
        client = c

        val connect = c.connectWith().cleanSession(true).keepAlive(30)
        val send = if (config.user.isNotEmpty()) {
            connect.simpleAuth()
                .username(config.user)
                .password(config.pass.toByteArray())
                .applySimpleAuth()
        } else connect
        log("broker", "connecting to ${config.host}:${config.port}...")
        send.send().whenComplete { _, err ->
            if (err != null) log("broker", "connect failed: ${err.message ?: err.javaClass.simpleName}")
        }
    }

    fun disconnect() {
        pendingAcks.values.forEach { it.cancel() }
        pendingAcks.clear()
        forgetActiveSubscriptions()
        client?.disconnect()
        client = null
        connected.value = false
    }

    fun setSubscriptionPolicy(policy: SubscriptionPolicy) {
        desiredPolicy = policy
        reconcileSubscriptions()
    }

    private fun onConnected() {
        connected.value = true
        forgetActiveSubscriptions()
        log("broker", "connected")
        reconcileSubscriptions()
    }

    /** The broker drops our subscriptions on disconnect (cleanSession), so the
     *  local record has to go with them or nothing would be re-subscribed. */
    private fun forgetActiveSubscriptions() {
        synchronized(subLock) { activeSubscriptions.clear() }
        activeFilters.value = emptySet()
    }

    private fun reconcileSubscriptions() {
        val c = client ?: return
        if (!connected.value) return
        val desired = desiredPolicy.filters()
        var changed = false
        var active = 0
        // send() is async, so the lock is held only for the bookkeeping.
        synchronized(subLock) {
            val stale = activeSubscriptions - desired
            val fresh = desired - activeSubscriptions
            stale.forEach { filter ->
                c.unsubscribeWith().topicFilter(filter).send()
                activeSubscriptions.remove(filter)
            }
            fresh.forEach { filter ->
                subscribe(c, filter)
                activeSubscriptions.add(filter)
            }
            changed = stale.isNotEmpty() || fresh.isNotEmpty()
            active = activeSubscriptions.size
            if (changed) activeFilters.value = activeSubscriptions.toSet()
        }
        if (changed) log("broker", "subscriptions $active active")
    }

    private fun subscribe(c: Mqtt3AsyncClient, filter: String) {
        c.subscribeWith()
            .topicFilter(filter)
            .qos(MqttQos.AT_LEAST_ONCE)
            .callback { pub ->
                val topic = pub.topic.toString()
                try {
                    val json = JSONObject(String(pub.payloadAsBytes))
                    if (TopicRouter.parse(topic) is Route.ModemAck) handleAck(json)
                    messages.tryEmit(topic to json)
                } catch (e: Exception) {
                    log("error", "bad payload on $topic: ${e.message}")
                }
            }
            .send()
    }

    // {id, action, args} at QoS 1; id format matches hmi.js ("c-" + base36 ts)
    fun publishCmd(mid: String, action: String, args: JSONObject): String {
        val id = "c-" + System.currentTimeMillis().toString(36)
        val payload = JSONObject().put("id", id).put("action", action).put("args", args)
        client?.publishWith()
            ?.topic(TopicRouter.modem(mid, "cmd"))
            ?.qos(MqttQos.AT_LEAST_ONCE)
            ?.payload(payload.toString().toByteArray())
            ?.send()
        cmdBanner.value = "$action -> $mid - waiting for ack..."
        log("cmd", "$mid $action ($id)")
        pendingAcks[id] = scope.launch {
            delay(10_000)
            pendingAcks.remove(id)
            cmdBanner.value = "gateway ack timeout (10 s)"
            log("ack", "TIMEOUT for $id")
        }
        return id
    }

    /** Retained publish for app-owned metadata (labels, tree). */
    fun publishRetained(topic: String, payload: JSONObject) {
        client?.publishWith()
            ?.topic(topic)
            ?.qos(MqttQos.AT_LEAST_ONCE)
            ?.retain(true)
            ?.payload(payload.toString().toByteArray())
            ?.send()
    }

    private fun handleAck(j: JSONObject) {
        val ack = Ack(j.optString("id", "?"), j.optBoolean("ok", false), j.optString("detail", ""))
        pendingAcks.remove(ack.id)?.cancel()
        lastAck.value = ack
        cmdBanner.value = if (ack.ok) "OK ${ack.detail}" else "refused: ${ack.detail}"
        log("ack", (if (ack.ok) "ok: " else "REFUSED: ") + ack.detail)
    }
}