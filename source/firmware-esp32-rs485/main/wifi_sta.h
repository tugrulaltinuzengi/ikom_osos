#pragma once
// Connect to the configured AP as a station. Waits up to 15 s for an IP,
// then returns either way ("0.0.0.0" while offline) so the gateway can boot
// and buffer telemetry without connectivity. Reconnects forever with
// exponential backoff (1 s -> 60 s).
const char *wifi_sta_start(void);
// Current IP as a static string; "0.0.0.0" until IP_EVENT_STA_GOT_IP.
const char *wifi_ip(void);
int wifi_rssi(void);
