// DKM-440 polling: esp-modbus RTU master, or simulated values (Kconfig).
// Register list, pacing (30 ms politeness gap + one retry) and float decoding
// mirror modbus/dkm_440_analyze/map.py, the confirmed TEDAS map.
#include <math.h>
#include <string.h>
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "meter.h"

static const char *TAG = "meter";

const meter_reg_t METER_REGS[METER_NUM_REGS] = {
    { "Supply_Voltage",     260 },
    { "MainBus_Voltage_L1", 100 },
    { "MainBus_Voltage_L2", 102 },
    { "MainBus_Voltage_L3", 104 },
    { "MainBus_Voltage_N",  106 },
    { "MainBus_Current_L1", 180 },
    { "MainBus_Current_L2", 182 },
    { "MainBus_Current_L3", 184 },
    { "MainBus_Current_N",  258 },
    { "MainBus_Freq_L1",    266 },
    { "MainBus_Freq_L2",    268 },
    { "MainBus_Freq_L3",    270 },
    { "MainBus_PF_L1",      272 },
    { "MainBus_PF_L2",      274 },
    { "MainBus_PF_L3",      276 },
    { "MainBus_CosPhi_L1",  350 },
    { "MainBus_CosPhi_L2",  352 },
    { "MainBus_CosPhi_L3",  354 },
    { "MainBus_TanPhi_Tot", 428 },
    { "MainBus_TanPhi_L1",  430 },
    { "MainBus_TanPhi_L2",  432 },
    { "MainBus_TanPhi_L3",  434 },
};

#if CONFIG_OSOS_SIM_MODE

void meter_init(void)
{
    ESP_LOGW(TAG, "SIM MODE: publishing synthetic values (menuconfig to disable)");
}

static float wob(float base, float amp)
{
    float t = (float)(esp_timer_get_time() / 1000000.0);
    float noise = ((int)(esp_random() % 1000) - 500) / 1500.0f * amp;
    return base + amp * sinf(t / 30.0f) + noise;
}

bool meter_read_all(float vals[METER_NUM_REGS], bool ok[METER_NUM_REGS])
{
    for (int i = 0; i < METER_NUM_REGS; i++) {
        const char *n = METER_REGS[i].name;
        float v;
        if (strstr(n, "Voltage_N")) v = wob(0.6f, 0.2f);
        else if (strstr(n, "Voltage")) v = wob(230.0f, 1.5f);
        else if (strstr(n, "Current_N")) v = wob(0.3f, 0.1f);
        else if (strstr(n, "Current")) v = wob(4.2f, 0.4f);
        else if (strstr(n, "Freq")) v = wob(50.0f, 0.02f);
        else if (strstr(n, "PF")) v = wob(0.92f, 0.02f);
        else if (strstr(n, "CosPhi")) v = wob(0.93f, 0.02f);
        else v = wob(0.40f, 0.03f); /* TanPhi */
        vals[i] = v;
        ok[i] = true;
    }
    return true;
}

#else  /* real Modbus */

#include "driver/uart.h"
#include "esp_modbus_master.h"
#include "esp_task_wdt.h"

#define READ_GAP_MS  30   /* map.py READ_GAP: the DKM-440 tarpits a hammering master */
#define READ_RETRIES 1    /* map.py READ_RETRIES */
// A dead meter must not stall the telemetry task for a whole 22-register
// sweep: after this many consecutive timeouts the cycle aborts early.
#define DEAD_ABORT_AFTER 3

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
    ESP_LOGI(TAG, "modbus master up: uart%d tx=%d rx=%d rts=%d %d 8N1 slave=%d",
             CONFIG_OSOS_MB_UART_PORT, CONFIG_OSOS_MB_TXD, CONFIG_OSOS_MB_RXD,
             CONFIG_OSOS_MB_RTS, CONFIG_OSOS_MB_BAUD, CONFIG_OSOS_MB_SLAVE_ID);
}

// map.py _read_one: FC03, 2 registers, WORD_ORDER="big" (high word first),
// one paced retry on a dropped read.
static bool read_one(int addr, float *out)
{
    for (int attempt = 0; attempt <= READ_RETRIES; attempt++) {
        uint16_t words[2] = { 0 };
        mb_param_request_t req = {
            .slave_addr = CONFIG_OSOS_MB_SLAVE_ID,
            .command = 0x03,
            .reg_start = addr,
            .reg_size = 2,
        };
        if (mbc_master_send_request(s_master, &req, words) == ESP_OK) {
            uint32_t raw = ((uint32_t)words[0] << 16) | words[1];
            memcpy(out, &raw, sizeof *out);
            // CRC-valid garbage happens on marginal RS-485 lines: a
            // non-finite float counts as a failed read (paced retry).
            if (isfinite(*out)) return true;
        }
        if (attempt < READ_RETRIES) vTaskDelay(pdMS_TO_TICKS(READ_GAP_MS));
    }
    return false;
}

bool meter_read_all(float vals[METER_NUM_REGS], bool ok[METER_NUM_REGS])
{
    bool any = false;
    int dead_streak = 0;
    for (int i = 0; i < METER_NUM_REGS; i++) {
        esp_task_wdt_reset(); /* no-op unless the calling task subscribed */
        ok[i] = read_one(METER_REGS[i].addr, &vals[i]);
        any |= ok[i];
        dead_streak = ok[i] ? 0 : dead_streak + 1;
        if (dead_streak >= DEAD_ABORT_AFTER) {
            ESP_LOGW(TAG, "%d consecutive timeouts — aborting sweep at %s",
                     dead_streak, METER_REGS[i].name);
            for (int j = i + 1; j < METER_NUM_REGS; j++) ok[j] = false;
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(READ_GAP_MS)); /* politeness gap */
    }
    return any;
}

#endif
