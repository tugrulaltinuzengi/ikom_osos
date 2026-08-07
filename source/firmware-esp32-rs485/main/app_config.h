#pragma once
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#define FW_VERSION "esp32s3-0.1.0"

#define TOPIC_FMT_TELEMETRY "osos/%s/telemetry"
#define TOPIC_FMT_STATUS    "osos/%s/status"
#define TOPIC_FMT_EVENT     "osos/%s/event"
#define TOPIC_FMT_CMD       "osos/%s/cmd"
#define TOPIC_FMT_ACK       "osos/%s/ack"

// telemetry task wake bits
#define BIT_READ_NOW  BIT0   // publish a frame immediately
#define BIT_INTERVAL  BIT1   // interval changed, restart the wait

extern EventGroupHandle_t app_events;

// current report interval in seconds (NVS-backed, set via cmd.c)
int report_interval_get(void);
void report_interval_set(int seconds);
