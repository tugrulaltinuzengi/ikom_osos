// MQTT link: retained status + LWT, cmd subscription, ack publishing.
// Topic scheme per docs/SRS_MQTT_METER_GATEWAY.md section 5.
#include <stdio.h>
#include <string.h>
#include "esp_crt_bundle.h"
#include "esp_log.h"
#include "mqtt_client.h"
#include "app_config.h"
#include "cmd.h"
#include "gw_mqtt.h"
#include "wifi_sta.h"

static const char *TAG = "gw_mqtt";
static esp_mqtt_client_handle_t s_client;
static bool s_connected = false;
static char s_topic_cmd[96];

// `leaf` is the last topic segment. "astatus" is the analyzer's status, which only
// exists in protocol v2 (in v1 there is one status topic for the whole gateway).
void gw_publish(const char *leaf, const char *json, int qos, bool retain)
{
    if (!s_client) return;
    char topic[128];
#if CONFIG_OSOS_PROTOCOL_V2
    if (!strcmp(leaf, "telemetry") || !strcmp(leaf, "profile")) {
        snprintf(topic, sizeof topic, "osos/m/%s/a/%s/%s", CONFIG_OSOS_GW_ID, CONFIG_OSOS_ANALYZER_ID, leaf);
    } else if (!strcmp(leaf, "astatus")) {
        snprintf(topic, sizeof topic, "osos/m/%s/a/%s/status", CONFIG_OSOS_GW_ID, CONFIG_OSOS_ANALYZER_ID);
    } else {
        snprintf(topic, sizeof topic, "osos/m/%s/%s", CONFIG_OSOS_GW_ID, leaf);
    }
#else
    if (!strcmp(leaf, "astatus")) return;
    snprintf(topic, sizeof topic, "osos/%s/%s", CONFIG_OSOS_GW_ID, leaf);
#endif
    esp_mqtt_client_publish(s_client, topic, json, 0, qos, retain);
}

bool gw_mqtt_connected(void) { return s_connected; }

static void publish_status_online(void)
{
    // IP is read at publish time (not cached at start): with the non-blocking
    // boot the lease may arrive, or change, after gw_mqtt_start().
    char json[200];
#if CONFIG_OSOS_PROTOCOL_V2
    snprintf(json, sizeof json,
             "{\"v\":2,\"state\":\"online\",\"fw\":\"%s\",\"bearer\":\"wifi\","
             "\"ip\":\"%s\",\"rssi\":%d,\"analyzers\":1}",
             FW_VERSION, wifi_ip(), wifi_rssi());
#else
    snprintf(json, sizeof json,
             "{\"state\":\"online\",\"fw\":\"%s\",\"bearer\":\"wifi\","
             "\"ip\":\"%s\",\"rssi\":%d}",
             FW_VERSION, wifi_ip(), wifi_rssi());
#endif
    gw_publish("status", json, 1, true);
#if CONFIG_OSOS_PROTOCOL_V2
    // v2 modem identity, retained: one analyzer on the RS-485 bus, no load channels.
    snprintf(json, sizeof json,
             "{\"v\":2,\"rev\":1,\"loads\":{\"channels\":0},\"analyzers\":[{\"id\":\"%s\","
             "\"host\":\"rs485\",\"port\":0,\"unit\":%d,\"interval\":%d}]}",
             CONFIG_OSOS_ANALYZER_ID, CONFIG_OSOS_MB_SLAVE_ID, report_interval_get());
    gw_publish("registry", json, 1, true);
    snprintf(json, sizeof json,
             "{\"v\":2,\"sleep\":false,\"interval\":%d,\"loads\":[],\"since\":\"\"}",
             report_interval_get());
    gw_publish("state", json, 1, true);
#endif
}

static void on_mqtt(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    esp_mqtt_event_handle_t ev = data;
    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "connected to broker");
        s_connected = true;
        publish_status_online();
        esp_mqtt_client_subscribe(s_client, s_topic_cmd, 1);
        app_publish_profile();
        gw_publish("event", "{\"type\":\"boot\"}", 1, false);
        break;
    case MQTT_EVENT_DISCONNECTED:
        s_connected = false;
        break;
    case MQTT_EVENT_DATA:
        if (ev->topic_len == strlen(s_topic_cmd) &&
            !strncmp(ev->topic, s_topic_cmd, ev->topic_len)) {
            cmd_handle(ev->data, ev->data_len);
        }
        break;
    default:
        break;
    }
}

void gw_mqtt_start(void)
{
    snprintf(s_topic_cmd, sizeof s_topic_cmd, TOPIC_FMT_CMD, CONFIG_OSOS_GW_ID);

    static char lwt_topic[96];
    snprintf(lwt_topic, sizeof lwt_topic, TOPIC_FMT_STATUS, CONFIG_OSOS_GW_ID);

    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = CONFIG_OSOS_MQTT_URI,
        .broker.verification.crt_bundle_attach = esp_crt_bundle_attach,
        .credentials = {
            .username = CONFIG_OSOS_MQTT_USER[0] ? CONFIG_OSOS_MQTT_USER : NULL,
            .client_id = CONFIG_OSOS_GW_ID,
            .authentication.password = CONFIG_OSOS_MQTT_PASS[0] ? CONFIG_OSOS_MQTT_PASS : NULL,
        },
        .session = {
            .keepalive = 30,
            .last_will = {
                .topic = lwt_topic,
#if CONFIG_OSOS_PROTOCOL_V2
                .msg = "{\"v\":2,\"state\":\"offline\"}",
#else
                .msg = "{\"state\":\"offline\"}",
#endif
                .qos = 1,
                .retain = true,
            },
        },
    };
    s_client = esp_mqtt_client_init(&cfg);
    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, on_mqtt, NULL);
    ESP_ERROR_CHECK(esp_mqtt_client_start(s_client));
}
