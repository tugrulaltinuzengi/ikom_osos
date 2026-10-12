// OSOS gateway firmware: DKM-440 --RS485/Modbus--> ESP32-S3 --MQTT/TLS--> cloud.
// The PC-free runtime of the osos_emu project; protocol identical to
// tools/fake_gateway.py (the PC reference implementation).
#include <stdio.h>
#include <stdlib.h>
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
#include "profile.h"
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
    // The profile is read here and replaced by the MQTT task: hold its lock for the
    // whole sweep so the register list cannot change underneath it.
    static osos_poll_result_t res;          // 48 doubles + flags: too big for the task stack
    profile_lock();
    meter_poll(&res);
    f->generation = profile_generation();
    int n = profile_count();
    profile_unlock();
    bool any = res.ok_count > 0;

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
    for (int i = 0; i < n; i++) {
        if (res.ok[i]) f->ok_mask |= (uint64_t)1 << i;
        f->vals[i] = res.value[i];
    }
}

// The retained analyzer status (protocol v2), republished when it changes.
static void publish_analyzer_status(bool meter_ok, const char *ts)
{
#if CONFIG_OSOS_PROTOCOL_V2
    static int last_state = -1;
    static uint32_t last_gen;
    uint32_t gen = profile_generation();
    if (last_state == (int)meter_ok && last_gen == gen) return;
    last_state = (int)meter_ok;
    last_gen = gen;
    char json[220];
    snprintf(json, sizeof json,
             "{\"v\":2,\"state\":\"%s\",\"host\":\"rs485\",\"unit\":%d,\"last_ok\":\"%s\","
             "\"fail_streak\":0,\"profile\":\"%s\"}",
             meter_ok ? "online" : "fault", CONFIG_OSOS_MB_SLAVE_ID, ts, profile_id());
    gw_publish("astatus", json, 1, true);
#else
    (void)meter_ok; (void)ts;
#endif
}

static void publish_frame(const telem_frame_t *f, bool buffered)
{
    // Register names come from the profile that captured this frame. If another has
    // taken over since, the frame no longer fits it: drop it rather than mislabel it.
    profile_lock();
    if (f->generation != profile_generation()) {
        profile_unlock();
        return;
    }
    const osos_reg_t *regs = profile_regs();
    int n = profile_count();
    cJSON *root = cJSON_CreateObject();
    char ts[24];
    iso_from((time_t)f->epoch, ts, sizeof ts);
#if CONFIG_OSOS_PROTOCOL_V2
    cJSON_AddNumberToObject(root, "v", 2);
#endif
    cJSON_AddStringToObject(root, "ts", ts);
    cJSON_AddNumberToObject(root, "seq", f->seq);
    cJSON_AddBoolToObject(root, "buffered", buffered);
    cJSON_AddStringToObject(root, "profile", profile_id());
    cJSON_AddNumberToObject(root, "profile_rev", profile_header()->rev);
    cJSON *values = cJSON_AddObjectToObject(root, "values");
    for (int i = 0; i < n; i++) {
        if (f->ok_mask & ((uint64_t)1 << i)) {
            // Printed with the register's own decimals, as raw JSON: cJSON's own number
            // printing would show 1234567.8900000001.
            char num[40];
            osos_format(f->vals[i], regs[i].decimals, num, sizeof num);
            cJSON_AddRawToObject(values, regs[i].key, num);
        } else {
            cJSON_AddNullToObject(values, regs[i].key);
        }
    }
    profile_unlock();
    cJSON_AddBoolToObject(root, "meter_ok", f->meter_ok);
    char *json = cJSON_PrintUnformatted(root);
    if (json) {
        gw_publish("telemetry", json, 1, false);
        cJSON_free(json);
    }
    cJSON_Delete(root);
    if (!buffered) publish_analyzer_status(f->meter_ok, ts);
}

// ---- meter profile publishing -------------------------------------------------
// Retained `profile` (the profile JSON, verbatim, so any app can label the values and
// edit the profile) and `profiles` (what is stored, limits).
void app_publish_profile(void)
{
    int size = profile_blob_size();
    if (size > 0) {
        char *buf = malloc((size_t)size + 1);
        if (buf && profile_blob_read(0, (uint8_t *)buf, (size_t)size) == size) {
            buf[size] = 0;
            gw_publish("profile", buf, 1, true);
        }
        free(buf);
    } else {
        gw_publish("profile", "", 1, true);          // clears the retained copy
    }
    cJSON *doc = cJSON_CreateObject();
    cJSON_AddNumberToObject(doc, "v", 2);
    cJSON *arr = cJSON_AddArrayToObject(doc, "profiles");
    cJSON *it = cJSON_CreateObject();
    cJSON_AddStringToObject(it, "id", profile_id());
    cJSON_AddNumberToObject(it, "rev", profile_header()->rev);
    cJSON_AddNumberToObject(it, "n", profile_count());
    cJSON_AddStringToObject(it, "name", profile_header()->name);
    if (profile_is_builtin()) cJSON_AddTrueToObject(it, "builtin");
    cJSON_AddItemToArray(arr, it);
#if CONFIG_OSOS_PROTOCOL_V2
    cJSON *as = cJSON_AddObjectToObject(doc, "assign");
    cJSON_AddStringToObject(as, CONFIG_OSOS_ANALYZER_ID, profile_id());
#endif
    cJSON *cap = cJSON_AddObjectToObject(doc, "cap");
    cJSON_AddNumberToObject(cap, "regs", OSOS_MAX_REGS);
    cJSON_AddNumberToObject(cap, "profiles", 1);
    cJSON_AddNumberToObject(cap, "blob", PROFILE_MAX_BLOB);
    char *json = cJSON_PrintUnformatted(doc);
    if (json) {
        gw_publish("profiles", json, 1, true);
        cJSON_free(json);
    }
    cJSON_Delete(doc);
}

void app_profile_changed(void)
{
    buf_clear();                                      // queued frames belong to the old profile
    app_publish_profile();
    gw_publish("event", "{\"type\":\"profile_changed\"}", 1, false);
    xEventGroupSetBits(app_events, BIT_READ_NOW);     // first frame under the new profile, now
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
    profile_nvs_init();
    profile_init();

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
