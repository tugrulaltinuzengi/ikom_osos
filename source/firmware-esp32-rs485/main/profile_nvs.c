// ESP-IDF side of profile.c: storage in NVS, and the lock.
//
// The profile lives in its own NVS partition ("profiles", see partitions.csv),
// separate from the default one that holds the report interval, so a profile of up
// to ~11 KB (registers + display metadata, rewritten in full on every upload)
// cannot crowd out anything else. If the partition is missing (an older partition
// table) every write fails, uploads are refused with "flash write failed", and the
// built-in DKM-440 keeps working.
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "profile.h"

static const char *TAG = "profile_nvs";
#define PART "profiles"
#define NS   "osos"

static SemaphoreHandle_t s_mutex;
static bool s_ready;

void profile_nvs_init(void)
{
    if (!s_mutex) s_mutex = xSemaphoreCreateRecursiveMutex();
    esp_err_t err = nvs_flash_init_partition(PART);
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase_partition(PART));
        err = nvs_flash_init_partition(PART);
    }
    s_ready = (err == ESP_OK);
    if (!s_ready) {
        ESP_LOGW(TAG, "no \"%s\" partition (%s): uploaded profiles cannot be stored, built-in DKM-440 only",
                 PART, esp_err_to_name(err));
    }
}

void profile_lock(void)
{
    if (s_mutex) xSemaphoreTakeRecursive(s_mutex, portMAX_DELAY);
}

void profile_unlock(void)
{
    if (s_mutex) xSemaphoreGiveRecursive(s_mutex);
}

bool profile_store_read(const char *key, void *buf, size_t *len)
{
    if (!s_ready) return false;
    nvs_handle_t h;
    if (nvs_open_from_partition(PART, NS, NVS_READONLY, &h) != ESP_OK) return false;
    esp_err_t e = nvs_get_blob(h, key, buf, len);
    nvs_close(h);
    return e == ESP_OK;
}

bool profile_store_write(const char *key, const void *buf, size_t len)
{
    if (!s_ready) return false;
    nvs_handle_t h;
    if (nvs_open_from_partition(PART, NS, NVS_READWRITE, &h) != ESP_OK) return false;
    esp_err_t e = nvs_set_blob(h, key, buf, len);
    if (e == ESP_OK) e = nvs_commit(h);
    nvs_close(h);
    if (e != ESP_OK) ESP_LOGE(TAG, "write %s (%u B): %s", key, (unsigned)len, esp_err_to_name(e));
    return e == ESP_OK;
}

bool profile_store_erase(const char *key)
{
    if (!s_ready) return false;
    nvs_handle_t h;
    if (nvs_open_from_partition(PART, NS, NVS_READWRITE, &h) != ESP_OK) return false;
    esp_err_t e = nvs_erase_key(h, key);
    if (e == ESP_OK) e = nvs_commit(h);
    nvs_close(h);
    return e == ESP_OK;
}
