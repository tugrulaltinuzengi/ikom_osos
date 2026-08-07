#pragma once
#include <stdbool.h>

void gw_mqtt_start(void);
bool gw_mqtt_connected(void);
// Publish helpers (topic name without the osos/{gw}/ prefix).
void gw_publish(const char *subtopic, const char *json, int qos, bool retain);
