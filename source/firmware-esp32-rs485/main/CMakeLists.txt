idf_component_register(
    SRCS "app_main.c" "wifi_sta.c" "meter.c" "gw_mqtt.c" "cmd.c" "http_ui.c" "buffer.c"
         "profile.c" "profile_nvs.c"
    # firmware-common holds the codec and the built-in profile, shared with the ESP8266 gateway
    INCLUDE_DIRS "." "../../firmware-common"
)

# Flash the web UI (../../www) as the "www" SPIFFS partition.
spiffs_create_partition_image(www ${CMAKE_CURRENT_SOURCE_DIR}/../../www FLASH_IN_PROJECT)
