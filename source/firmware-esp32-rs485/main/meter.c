// Meter polling over RS-485 (esp-modbus RTU master), or simulated values (Kconfig).
//
// What is read and how it is decoded comes from the active profile (profile.c) and
// the shared codec (firmware-common/osos_codec.h): request merging, function codes
// 03/04, word and byte order, scale and offset, and the "stop after three dead
// registers" rule are the same code the ESP8266 gateway runs, tested on a PC
// against source/meter-profiles/vectors.json.
#include <math.h>
#include <string.h>
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "meter.h"
#include "profile.h"

static const char *TAG = "meter";

// A sweep that has run this long stops, so the telemetry task is back at its
// watchdog and the MQTT keepalive well in time even when the meter is slow.
#define POLL_BUDGET_MS 8000

#if CONFIG_OSOS_SIM_MODE

void meter_init(void)
{
    ESP_LOGW(TAG, "SIM MODE: publishing synthetic values (menuconfig to disable)");
}

static double wob(double base, double amp)
{
    double t = (double)(esp_timer_get_time() / 1000000.0);
    double noise = ((int)(esp_random() % 1000) - 500) / 1500.0 * amp;
    return base + amp * sin(t / 30.0) + noise;
}

// Plausible readings chosen from the register's key; a profile that is not a DKM-440
// still gets sensible-looking numbers.
static double sim_value(const char *n)
{
    if (strstr(n, "Voltage_N")) return wob(0.6, 0.2);
    if (strstr(n, "Voltage")) return wob(230.0, 1.5);
    if (strstr(n, "Current_N")) return wob(0.3, 0.1);
    if (strstr(n, "Current")) return wob(4.2, 0.4);
    if (strstr(n, "Freq")) return wob(50.0, 0.02);
    if (strstr(n, "Energy")) return 1234.5 + (esp_timer_get_time() / 1000000.0) / 3600.0 * 3.8;
    if (strstr(n, "Power")) return wob(3800.0, 200.0);
    if (strstr(n, "PF") || strstr(n, "CosPhi")) return wob(0.92, 0.02);
    if (strstr(n, "TanPhi")) return wob(0.40, 0.03);
    return wob(10.0, 1.0);
}

void meter_poll(osos_poll_result_t *res)
{
    const osos_reg_t *regs = profile_regs();
    int n = profile_count();
    res->ok_count = 0;
    res->gave_up = false;
    for (int i = 0; i < n; i++) {
        res->value[i] = sim_value(regs[i].key);
        res->ok[i] = true;
        res->ok_count++;
    }
}

bool meter_read_raw(uint8_t fc, uint16_t addr, uint16_t words, uint16_t *out)
{
    for (uint16_t i = 0; i < words; i++) out[i] = (uint16_t)(addr + i);   // recognisable dummy data
    return true;
}

#else  /* real Modbus */

#include "driver/uart.h"
#include "esp_modbus_master.h"
#include "esp_task_wdt.h"

static void *s_master = NULL;

void meter_init(void)
{
    mb_communication_info_t comm = {
        .ser_opts = {
            .port = CONFIG_OSOS_MB_UART_PORT,
            .mode = MB_RTU,
            .baudrate = CONFIG_OSOS_MB_BAUD,
            .parity = UART_PARITY_DISABLE,
            .data_bits = UART_DATA_8_BITS,
            .stop_bits = UART_STOP_BITS_1,
            .response_tout_ms = CONFIG_OSOS_MB_TIMEOUT_MS,
        },
    };
    ESP_ERROR_CHECK(mbc_master_create_serial(&comm, &s_master));
    ESP_ERROR_CHECK(uart_set_pin(CONFIG_OSOS_MB_UART_PORT, CONFIG_OSOS_MB_TXD,
                                 CONFIG_OSOS_MB_RXD, CONFIG_OSOS_MB_RTS,
                                 UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(mbc_master_start(s_master));
    ESP_ERROR_CHECK(uart_set_mode(CONFIG_OSOS_MB_UART_PORT, UART_MODE_RS485_HALF_DUPLEX));
    ESP_LOGI(TAG, "modbus master up: uart%d tx=%d rx=%d rts=%d %d 8N1 slave=%d (the profile's "
                  "timeout does not apply on RS-485: CONFIG_OSOS_MB_TIMEOUT_MS=%d)",
             CONFIG_OSOS_MB_UART_PORT, CONFIG_OSOS_MB_TXD, CONFIG_OSOS_MB_RXD,
             CONFIG_OSOS_MB_RTS, CONFIG_OSOS_MB_BAUD, CONFIG_OSOS_MB_SLAVE_ID, CONFIG_OSOS_MB_TIMEOUT_MS);
}

bool meter_read_raw(uint8_t fc, uint16_t addr, uint16_t words, uint16_t *out)
{
    if ((fc != 3 && fc != 4) || words < 1 || words > 64) return false;
    mb_param_request_t req = {
        .slave_addr = CONFIG_OSOS_MB_SLAVE_ID,
        .command = fc,
        .reg_start = addr,
        .reg_size = words,
    };
    return mbc_master_send_request(s_master, &req, out) == ESP_OK;
}

static bool poll_read(void *ctx, uint8_t fc, uint16_t start, uint16_t words, uint16_t *out)
{
    (void)ctx;
    esp_task_wdt_reset(); /* no-op unless the calling task subscribed */
    return meter_read_raw(fc, start, words, out);
}

// Between requests: the profile's read gap (the DKM-440 tarpits a master that fires
// back to back), then the time budget.
static bool poll_idle(void *ctx, uint16_t gap_ms)
{
    vTaskDelay(pdMS_TO_TICKS(gap_ms));
    return (esp_timer_get_time() - *(int64_t *)ctx) / 1000 < POLL_BUDGET_MS;
}

void meter_poll(osos_poll_result_t *res)
{
    int64_t started = esp_timer_get_time();
    osos_timing_t t = profile_timing();
    osos_io_t io = { poll_read, poll_idle, &started };
    osos_poll(profile_regs(), profile_count(), &t, &io, res);
    if (res->gave_up) {
        ESP_LOGW(TAG, "sweep stopped early: %d/%d registers answered", res->ok_count, profile_count());
    }
}

#endif
