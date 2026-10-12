# Host tests for the ESP32 gateway's profile store (main/profile.c): no ESP-IDF, no
# hardware. NVS is replaced by a map in memory; the same vectors.json as the other
# suites drive it.
#
#   make
CJSON_VERSION ?= 1.7.18
CACHE := .cache
CC ?= gcc
CFLAGS ?= -std=c11 -O1 -g -Wall -Wextra -Wno-unused-parameter -fsanitize=address,undefined \
          -I$(CACHE) -I../main -I../../firmware-common

.PHONY: all test clean
all: test

$(CACHE)/cJSON.c:
	mkdir -p $(CACHE)
	curl -fsSL -o $(CACHE)/cJSON.c https://raw.githubusercontent.com/DaveGamble/cJSON/v$(CJSON_VERSION)/cJSON.c
	curl -fsSL -o $(CACHE)/cJSON.h https://raw.githubusercontent.com/DaveGamble/cJSON/v$(CJSON_VERSION)/cJSON.h

test_profile: test_profile.c ../main/profile.c ../main/profile.h ../../firmware-common/osos_codec.h ../../firmware-common/osos_builtin_dkm440.h $(CACHE)/cJSON.c
	$(CC) $(CFLAGS) -o $@ test_profile.c ../main/profile.c $(CACHE)/cJSON.c -lm

test: test_profile
	./test_profile

clean:
	rm -rf test_profile $(CACHE)
