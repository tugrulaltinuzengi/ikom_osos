#include <string.h>
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "wifi_sta.h"

static const char *TAG = "wifi";
static EventGroupHandle_t s_events;
#define GOT_IP_BIT BIT0
// Bounded boot wait: without an AP the gateway still boots and buffers
// telemetry (store-and-forward); WiFi keeps retrying in the background.
#define BOOT_WAIT_MS 15000
static char s_ip[16] = "0.0.0.0";
static esp_timer_handle_t s_retry_timer;
// SRS FW-10: exponential reconnect backoff 1 s -> 60 s, reset on success.
static uint32_t s_backoff_ms = 1000;

static void retry_cb(void *arg)
{
    esp_wifi_connect();
}

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_events, GOT_IP_BIT);
        ESP_LOGW(TAG, "disconnected, retry in %lu ms", (unsigned long)s_backoff_ms);
        // One-shot timer instead of vTaskDelay: never blocks the shared
        // default event loop task.
        esp_timer_start_once(s_retry_timer, (uint64_t)s_backoff_ms * 1000);
        s_backoff_ms = s_backoff_ms >= 30000 ? 60000 : s_backoff_ms * 2;
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = data;
        snprintf(s_ip, sizeof s_ip, IPSTR, IP2STR(&ev->ip_info.ip));
        s_backoff_ms = 1000;
        ESP_LOGI(TAG, "got ip %s", s_ip);
        xEventGroupSetBits(s_events, GOT_IP_BIT);
    }
}

const char *wifi_sta_start(void)
{
    s_events = xEventGroupCreate();
    const esp_timer_create_args_t targs = { .callback = retry_cb, .name = "wifi_retry" };
    ESP_ERROR_CHECK(esp_timer_create(&targs, &s_retry_timer));
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi, NULL));

    wifi_config_t cfg = { 0 };
    strlcpy((char *)cfg.sta.ssid, CONFIG_OSOS_WIFI_SSID, sizeof cfg.sta.ssid);
    strlcpy((char *)cfg.sta.password, CONFIG_OSOS_WIFI_PASS, sizeof cfg.sta.password);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    if (!(xEventGroupWaitBits(s_events, GOT_IP_BIT, pdFALSE, pdTRUE,
                              pdMS_TO_TICKS(BOOT_WAIT_MS)) & GOT_IP_BIT)) {
        ESP_LOGW(TAG, "no IP after %d s — booting offline, will keep retrying",
                 BOOT_WAIT_MS / 1000);
    }
    return s_ip;
}

const char *wifi_ip(void)
{
    return s_ip;
}

int wifi_rssi(void)
{
    wifi_ap_record_t ap;
    return esp_wifi_sta_get_ap_info(&ap) == ESP_OK ? ap.rssi : 0;
}
