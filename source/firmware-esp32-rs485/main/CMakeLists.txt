idf_component_register(
    SRCS "app_main.c" "wifi_sta.c" "meter.c" "gw_mqtt.c" "cmd.c" "http_ui.c" "buffer.c"
    INCLUDE_DIRS "."
)

# Flash the web UI (../../www) as the "www" SPIFFS partition.
spiffs_create_partition_image(www ${CMAKE_CURRENT_SOURCE_DIR}/../../www FLASH_IN_PROJECT)
