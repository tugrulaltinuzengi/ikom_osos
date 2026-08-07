#include <stdio.h>
#include <string.h>
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_spiffs.h"
#include "http_ui.h"

static const char *TAG = "http_ui";

static const char *content_type(const char *path)
{
    const char *ext = strrchr(path, '.');
    if (!ext) return "text/plain";
    if (!strcmp(ext, ".html")) return "text/html";
    if (!strcmp(ext, ".js"))   return "application/javascript";
    if (!strcmp(ext, ".json")) return "application/json";
    if (!strcmp(ext, ".css"))  return "text/css";
    if (!strcmp(ext, ".png"))  return "image/png";
    if (!strcmp(ext, ".svg"))  return "image/svg+xml";
    return "application/octet-stream";
}

static esp_err_t file_get(httpd_req_t *req)
{
    char path[128] = "/www";
    if (!strcmp(req->uri, "/")) {
        strlcat(path, "/index.html", sizeof path);
    } else {
        // strip query string
        const char *q = strchr(req->uri, '?');
        size_t n = q ? (size_t)(q - req->uri) : strlen(req->uri);
        if (n > sizeof path - 5) n = sizeof path - 5;
        strncat(path, req->uri, n);
    }
    FILE *f = fopen(path, "rb");
    if (!f) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "not found");
        return ESP_OK;
    }
    httpd_resp_set_type(req, content_type(path));
    static char buf[4096];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) {
        if (httpd_resp_send_chunk(req, buf, n) != ESP_OK) break;
    }
    fclose(f);
    httpd_resp_send_chunk(req, NULL, 0);
    return ESP_OK;
}

void http_ui_start(void)
{
    esp_vfs_spiffs_conf_t spiffs = {
        .base_path = "/www",
        .partition_label = "www",
        .max_files = 4,
        .format_if_mount_failed = false,
    };
    esp_err_t err = esp_vfs_spiffs_register(&spiffs);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "spiffs mount failed (%s) — web UI disabled", esp_err_to_name(err));
        return;
    }
    httpd_handle_t server = NULL;
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.uri_match_fn = httpd_uri_match_wildcard;
    ESP_ERROR_CHECK(httpd_start(&server, &cfg));
    static const httpd_uri_t any = {
        .uri = "/*", .method = HTTP_GET, .handler = file_get,
    };
    httpd_register_uri_handler(server, &any);
    ESP_LOGI(TAG, "web UI on http://<ip>/");
}
