#!/usr/bin/env bash
# Compile the gateway sketch against the real ESP8266 Arduino core, without the Arduino
# IDE: downloads the core, toolchain and libraries into ./.toolchain (about 400 MB, once)
# and runs an object compile with -Wall -Wextra. Catches API misuse and type errors that
# the host tests (which have no Arduino) cannot. It does not link or flash.
#
#   ./compile_check.sh            # needs curl, tar, unzip
set -euo pipefail
cd "$(dirname "$0")"
T="$PWD/.toolchain"
CORE_VER=3.1.2
TC_URL=https://github.com/earlephilhower/esp-quick-toolchain/releases/download/3.1.0-gcc10.3/x86_64-linux-gnu.xtensa-lx106-elf-e5f9fec.220621.tar.gz
AJ_URL=https://github.com/bblanchon/ArduinoJson/releases/download/v7.0.4/ArduinoJson-v7.0.4.h
PSC=https://raw.githubusercontent.com/knolleary/pubsubclient/v2.8/src

mkdir -p "$T"
[ -d "$T/core/esp8266-$CORE_VER" ] || { mkdir -p "$T/core"; curl -fsSL -o "$T/core.zip" "https://github.com/esp8266/Arduino/releases/download/$CORE_VER/esp8266-$CORE_VER.zip"; unzip -q "$T/core.zip" -d "$T/core"; }
[ -d "$T/tc/xtensa-lx106-elf" ] || { mkdir -p "$T/tc"; curl -fsSL -o "$T/tc.tgz" "$TC_URL"; tar -xzf "$T/tc.tgz" -C "$T/tc"; }
mkdir -p "$T/libs/ArduinoJson/src" "$T/libs/PubSubClient/src"
[ -f "$T/libs/ArduinoJson/src/ArduinoJson.h" ] || curl -fsSL -o "$T/libs/ArduinoJson/src/ArduinoJson.h" "$AJ_URL"
for f in PubSubClient.h PubSubClient.cpp; do [ -f "$T/libs/PubSubClient/src/$f" ] || curl -fsSL -o "$T/libs/PubSubClient/src/$f" "$PSC/$f"; done

C="$T/core/esp8266-$CORE_VER"
SK="$T/sketch"
rm -rf "$SK" && mkdir -p "$SK" && cp ../osos_gw8266/* "$SK/"
[ -f "$SK/config.h" ] || cp "$SK/config.h.example" "$SK/config.h"
{ echo '#include <Arduino.h>'; cat "$SK/osos_gw8266.ino"; } > "$T/sketch.cpp"

INC="-I$SK -I$C/tools/sdk/include -I$C/tools/sdk/lwip2/include -I$C/tools/sdk/libc/xtensa-lx106-elf/include -I$C/cores/esp8266 -I$C/variants/nodemcu"
for l in ESP8266WiFi/src LittleFS/src EEPROM; do INC="$INC -I$C/libraries/$l"; done
INC="$INC -I$T/libs/PubSubClient/src -I$T/libs/ArduinoJson/src"
"$T/tc/xtensa-lx106-elf/bin/xtensa-lx106-elf-g++" -c -Os -g -free -fipa-pta -Wpointer-arith -Wno-psabi -Wshadow=local \
  -Werror=return-type -fno-rtti -fno-exceptions -std=gnu++17 -mlongcalls -mtext-section-literals -falign-functions=4 \
  -ffunction-sections -fdata-sections -DF_CPU=80000000L -DLWIP_OPEN_SRC -DTCP_MSS=536 -DLWIP_FEATURES=1 -DLWIP_IPV6=0 \
  -DARDUINO=10607 -DARDUINO_ESP8266_NODEMCU_ESP12E -DARDUINO_ARCH_ESP8266 '-DARDUINO_BOARD="ESP8266_NODEMCU_ESP12E"' \
  -DLED_BUILTIN=2 -DFLASHMODE_DIO -DESP8266 -DNONOSDK22x_190703=1 -DUMM_STATS_FULL=1 -DMMU_IRAM_SIZE=0x8000 \
  $INC -Wall -Wextra -Wno-unused-parameter "$T/sketch.cpp" -o "$T/sketch.o"
"$T/tc/xtensa-lx106-elf/bin/xtensa-lx106-elf-size" "$T/sketch.o"
echo "sketch compiles"
