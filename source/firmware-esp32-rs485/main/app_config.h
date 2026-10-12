#pragma once
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#define FW_VERSION "esp32s3-0.2.0"

// Topic scheme. Protocol v1 (default, unchanged): osos/{gw}/{telemetry|status|event|cmd|ack}.
// Protocol v2 (CONFIG_OSOS_PROTOCOL_V2): this gateway is modem {gw} with one analyzer,
// so the app and the browser meter-map window can manage it like any other modem:
//   osos/m/{gw}/{status|registry|state|event|cmd|ack|profiles}
//   osos/m/{gw}/a/{CONFIG_OSOS_ANALYZER_ID}/{telemetry|status|profile}
#if CONFIG_OSOS_PROTOCOL_V2
#define TOPIC_FMT_STATUS    "osos/m/%s/status"
#define TOPIC_FMT_CMD       "osos/m/%s/cmd"
#else
#define TOPIC_FMT_STATUS    "osos/%s/status"
#define TOPIC_FMT_CMD       "osos/%s/cmd"
#endif

// telemetry task wake bits
#define BIT_READ_NOW  BIT0   // publish a frame immediately
#define BIT_INTERVAL  BIT1   // interval changed, restart the wait

extern EventGroupHandle_t app_events;

// current report interval in seconds (NVS-backed, set via cmd.c)
int report_interval_get(void);
void report_interval_set(int seconds);

// The active meter profile changed (committed, deleted): drop buffered frames, tell the
// broker. Implemented in app_main.c; called from the command handler.
void app_profile_changed(void);
// Republish the retained profile and profile list without changing anything.
void app_publish_profile(void);
