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
