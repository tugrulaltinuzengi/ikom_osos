// Phase-1 command set: read_now, set_interval, ping. Everything else is
// refused with ok:false (never silence — SRS FW rules). relay/dkm_write are
// deliberately NOT implemented while the recognizer can misread.
#include <stdio.h>
#include <string.h>
#include "cJSON.h"
#include "esp_log.h"
#include "nvs.h"
#include "app_config.h"
#include "cmd.h"
#include "gw_mqtt.h"
#include "meter.h"
#include "profile.h"

static const char *TAG = "cmd";

// Built with cJSON (not snprintf) so a hostile/odd cmd id with quotes or
// backslashes can't produce malformed ack JSON.
static void ack(const char *id, bool ok, const char *detail)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "id", id);
    cJSON_AddBoolToObject(root, "ok", ok);
    cJSON_AddStringToObject(root, "detail", detail);
    char *json = cJSON_PrintUnformatted(root);
    if (json) {
        gw_publish("ack", json, 1, false);
        cJSON_free(json);
    }
    cJSON_Delete(root);
}

void cmd_handle(const char *data, int len)
{
    cJSON *root = cJSON_ParseWithLength(data, len);
    if (!root) {
        ack("?", false, "invalid json");
        return;
    }
    const cJSON *jid = cJSON_GetObjectItem(root, "id");
    const cJSON *jaction = cJSON_GetObjectItem(root, "action");
    const char *id = cJSON_IsString(jid) ? jid->valuestring : "?";
    const char *action = cJSON_IsString(jaction) ? jaction->valuestring : "";
    const cJSON *args = cJSON_GetObjectItem(root, "args");
    ESP_LOGI(TAG, "cmd %s: %s", id, action);

    char detail[96];
    // Meter profiles: upload, delete, test read. Same commands and ack texts as the
    // ESP8266 gateway (profile.c / profile_store.h), so one UI manages both.
    profile_result_t pr = profile_handle(action, args);
    if (pr.handled) {
        bool ok = pr.ok;
        snprintf(detail, sizeof detail, "%s", pr.detail);
        if (pr.ok && pr.want_test) {
            uint8_t words = pr.test_raw_words ? pr.test_raw_words : osos_type_words(pr.test_reg.type);
            uint16_t w[8] = { 0 };
            if (meter_read_raw(pr.test_reg.fc, pr.test_reg.address, words, w)) {
                profile_describe_test(&pr, w, words, detail, sizeof detail);
            } else {
                ok = false;
                snprintf(detail, sizeof detail, "read failed (no answer from the meter)");
            }
        }
        ack(id, ok, detail);
        if (pr.ok && pr.changed) app_profile_changed();
        cJSON_Delete(root);
        return;
    }
    if (!strcmp(action, "read_now")) {
        xEventGroupSetBits(app_events, BIT_READ_NOW);
        ack(id, true, "reading now");
    } else if (!strcmp(action, "set_interval")) {
        const cJSON *js = args ? cJSON_GetObjectItem(args, "seconds") : NULL;
        int s = cJSON_IsNumber(js) ? js->valueint : 0;
        if (s >= 1 && s <= 900) {
            report_interval_set(s);
            xEventGroupSetBits(app_events, BIT_INTERVAL);
            snprintf(detail, sizeof detail, "interval=%ds (persisted)", s);
            ack(id, true, detail);
        } else {
            ack(id, false, "seconds out of range 1..900");
        }
    } else if (!strcmp(action, "ping")) {
        snprintf(detail, sizeof detail, "alive, interval=%ds, fw=%s",
                 report_interval_get(), FW_VERSION);
        ack(id, true, detail);
    } else {
        snprintf(detail, sizeof detail, "'%.24s' not supported in phase 1", action);
        ack(id, false, detail);
    }
    cJSON_Delete(root);
}
