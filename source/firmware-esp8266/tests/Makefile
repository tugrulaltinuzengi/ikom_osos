# Host-side tests for the gateway's meter-profile code. No Arduino, no hardware:
# osos_codec.h and profile_store.h compile on a PC, and this runs them against the
# same vectors.json as the Python and JavaScript suites.
#
#   make            # downloads ArduinoJson once, builds, runs
#   make clean
ARDUINOJSON_VERSION ?= 7.0.4
CACHE := .cache
AJ := $(CACHE)/ArduinoJson.h
CXX ?= g++
CXXFLAGS ?= -std=c++17 -O1 -g -Wall -Wextra -Wno-unused-parameter -fsanitize=address,undefined \
            -I$(CACHE) -I../osos_gw8266

.PHONY: all test clean
all: test

$(AJ):
	mkdir -p $(CACHE)
	curl -fsSL -o $(AJ) https://github.com/bblanchon/ArduinoJson/releases/download/v$(ARDUINOJSON_VERSION)/ArduinoJson-v$(ARDUINOJSON_VERSION).h

test_firmware: test_firmware.cpp host_fs.h ../osos_gw8266/profile_store.h ../osos_gw8266/osos_codec.h $(AJ)
	$(CXX) $(CXXFLAGS) -o $@ test_firmware.cpp

test: test_firmware
	./test_firmware

clean:
	rm -rf test_firmware $(CACHE)
