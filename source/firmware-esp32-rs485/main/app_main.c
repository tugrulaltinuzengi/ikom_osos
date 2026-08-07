// OSOS gateway firmware: DKM-440 --RS485/Modbus--> ESP32-S3 --MQTT/TLS--> cloud.
// The PC-free runtime of the osos_emu project; protocol identical to
// tools/fake_gateway.py (the PC reference implementation).
#include <stdio.h>
#include <string.h>
#include <time.h>
#include "cJSON.h"
#include "esp_log.h"
#include "esp_netif_sntp.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mdns.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "app_config.h"
#include "buffer.h"
#include "cmd.h"
#include "gw_mqtt.h"
#include "http_ui.h"
#include "meter.h"
#include "wifi_sta.h"

static const char *TAG = "app";

EventGroupHandle_t app_events;
static int s_interval = CONFIG_OSOS_REPORT_INTERVAL;

int report_interval_get(void) { return s_interval; }

void report_interval_set(int seconds)
{
    s_interval = seconds;
    nvs_handle_t h;
    if (nvs_open("osos", NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_i32(h, "interval", seconds);
        nvs_commit(h);
        nvs_close(h);
    }
}

static void report_interval_load(void)
{
    nvs_handle_t h;
    int32_t v = 0;
    if (nvs_open("osos", NVS_READONLY, &h) == ESP_OK) {
        if (nvs_get_i32(h, "interval", &v) == ESP_OK && v >= 1 && v <= 900) {
            s_interval = v;
        }
        nvs_close(h);
    }
}

static void iso_from(time_t t, char *buf, size_t n)
{
    struct tm tm;
    gmtime_r(&t, &tm);
    strftime(buf, n, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

// seq is monotonic per boot whether or not the frame could be published, so
// the head-end can see outage gaps (v0.1 only counted published frames).
static uint32_t s_seq = 0;

static void frame_capture(telem_frame_t *f)
{
    float vals[METER_NUM_REGS];
    bool ok[METER_NUM_REGS];
    bool any = meter_read_all(vals, ok);

    static bool was_ok = true;
    if (was_ok && !any) {
        gw_publish("event", "{\"type\":\"meter_link_lost\"}", 1, false);
    } else if (!was_ok && any) {
        gw_publish("event", "{\"type\":\"meter_link_restored\"}", 1, false);
    }
    was_ok = any;

    f->epoch = time(NULL);
    f->seq = ++s_seq;
    f->meter_ok = any;
    f->ok_mask = 0;
    for (int i = 0; i < METER_NUM_REGS; i++) {
        if (ok[i]) f->ok_mask |= 1u << i;
        f->vals[i] = vals[i];
    }
}

static void publish_frame(const telem_frame_t *f, bool buffered)
{
    cJSON *root = cJSON_CreateObject();
    char ts[24];
    iso_from((time_t)f->epoch, ts, sizeof ts);
    cJSON_AddStringToObject(root, "ts", ts);
    cJSON_AddNumberToObject(root, "seq", f->seq);
    cJSON_AddBoolToObject(root, "buffered", buffered);
    cJSON *values = cJSON_AddObjectToObject(root, "values");
    for (int i = 0; i < METER_NUM_REGS; i++) {
        if (f->ok_mask & (1u << i)) {
            float v = f->vals[i];
            cJSON_AddNumberToObject(values, METER_REGS[i].name,
                                    ((int)(v * 100 + (v >= 0 ? 0.5 : -0.5))) / 100.0);
        } else {
            cJSON_AddNullToObject(values, METER_REGS[i].name);
        }
    }
    cJSON_AddBoolToObject(root, "meter_ok", f->meter_ok);
    char *json = cJSON_PrintUnformatted(root);
    if (json) {
        gw_publish("telemetry", json, 1, false);
        cJSON_free(json);
    }
    cJSON_Delete(root);
}

// Flush the offline backlog oldest-first, paced so the esp-mqtt QoS-1 outbox
// doesn't balloon (512 frames -> ~25 s worst case).
static void flush_buffered(void)
{
    telem_frame_t old;
    int flushed = 0;
    while (gw_mqtt_connected() && buf_pop(&old)) {
        publish_frame(&old, true);
        flushed++;
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    if (flushed > 0) {
        char json[64];
        snprintf(json, sizeof json, "{\"type\":\"buffer_flush\",\"count\":%d}", flushed);
        gw_publish("event", json, 1, false);
        ESP_LOGI(TAG, "flushed %d buffered frames", flushed);
    }
}

// Wait one report interval in <=2 s slices so the task watchdog stays fed
// even at the 900 s maximum interval. Returns early on read_now / interval.
static void interval_wait(void)
{
    int64_t deadline = esp_timer_get_time() + (int64_t)report_interval_get() * 1000000;
    for (;;) {
        esp_task_wdt_reset();
        int64_t remain_ms = (deadline - esp_timer_get_time()) / 1000;
        if (remain_ms <= 0) return;
        if (remain_ms > 2000) remain_ms = 2000;
        if (xEventGroupWaitBits(app_events, BIT_READ_NOW | BIT_INTERVAL,
                                pdTRUE, pdFALSE, pdMS_TO_TICKS((uint32_t)remain_ms))) {
            return;
        }
    }
}

static void telemetry_task(void *arg)
{
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));
    for (;;) {
        esp_task_wdt_reset();
        telem_frame_t f;
        frame_capture(&f);
        if (gw_mqtt_connected()) {
            flush_buffered();
            publish_frame(&f, false);
            ESP_LOGI(TAG, "telemetry seq=%lu meter_ok=%d",
                     (unsigned long)f.seq, f.meter_ok);
        } else {
            buf_push(&f);
            ESP_LOGW(TAG, "offline: buffered seq=%lu (%d queued)",
                     (unsigned long)f.seq, buf_count());
        }
        interval_wait();
    }
}

// mDNS: fixes the "IP changes every reboot" problem for the browser HMI —
// the page is always at http://{gw-id}.local/ regardless of the DHCP lease.
static void start_mdns(void)
{
    if (mdns_init() != ESP_OK) {
        ESP_LOGW(TAG, "mdns init failed");
        return;
    }
    mdns_hostname_set(CONFIG_OSOS_GW_ID);
    mdns_instance_name_set("OSOS DKM-440 gateway");
    mdns_service_add(NULL, "_http", "_tcp", 80, NULL, 0);
    ESP_LOGI(TAG, "mdns: http://%s.local/", CONFIG_OSOS_GW_ID);
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }
    app_events = xEventGroupCreate();
    report_interval_load();

    const char *ip = wifi_sta_start();
    start_mdns();

    esp_sntp_config_t sntp = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
    esp_netif_sntp_init(&sntp);
    if (esp_netif_sntp_sync_wait(pdMS_TO_TICKS(10000)) != ESP_OK) {
        ESP_LOGW(TAG, "sntp sync timeout — timestamps start at epoch");
    }

    meter_init();
    gw_mqtt_start();
    http_ui_start();

    xTaskCreate(telemetry_task, "telemetry", 6144, NULL, 5, NULL);
    ESP_LOGI(TAG, "gateway %s up, interval %ds, ui http://%s/ (http://%s.local/)",
             CONFIG_OSOS_GW_ID, s_interval, ip, CONFIG_OSOS_GW_ID);
}
