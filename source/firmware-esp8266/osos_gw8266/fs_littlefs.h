// OsosFs on the ESP8266's LittleFS partition. Choose a flash layout that has a
// filesystem (Arduino IDE: Tools > Flash Size > "4MB (FS:1MB OTA:~1019KB)").
// Without one the gateway still runs: it just can't store uploaded profiles and
// falls back to the compiled-in DKM-440.
#pragma once

#include <LittleFS.h>
#include "profile_store.h"

class LittleFsAdapter : public OsosFs {
 public:
  bool begin() {
    ready_ = LittleFS.begin();           // formats an empty partition on first use
    if (ready_ && !LittleFS.exists(OSOS_PF_DIR)) LittleFS.mkdir(OSOS_PF_DIR);
    return ready_;
  }
  bool ready() const { return ready_; }

  int size(const char* path) override {
    if (!ready_) return -1;
    File f = LittleFS.open(path, "r");
    if (!f) return -1;
    const int n = (int)f.size();
    f.close();
    return n;
  }
  bool write(const char* path, const void* data, size_t n, bool append) override {
    if (!ready_) return false;
    File f = LittleFS.open(path, append ? "a" : "w");
    if (!f) return false;
    const size_t w = f.write((const uint8_t*)data, n);
    f.close();
    return w == n;
  }
  int read(const char* path, size_t off, void* data, size_t n) override {
    if (!ready_) return -1;
    File f = LittleFS.open(path, "r");
    if (!f) return -1;
    if (!f.seek(off, SeekSet)) { f.close(); return -1; }
    const int got = (int)f.read((uint8_t*)data, n);
    f.close();
    return got;
  }
  bool remove(const char* path) override { return ready_ && LittleFS.remove(path); }
  bool rename(const char* from, const char* to) override { return ready_ && LittleFS.rename(from, to); }
  size_t freeBytes() override {
    if (!ready_) return 0;
    FSInfo info;
    if (!LittleFS.info(info)) return 0;
    return info.totalBytes - info.usedBytes;
  }
  void list(const char* dir, void (*cb)(const char*, void*), void* ctx) override {
    if (!ready_) return;
    Dir d = LittleFS.openDir(dir);
    while (d.next()) cb(d.fileName().c_str(), ctx);
  }

 private:
  bool ready_ = false;
};
