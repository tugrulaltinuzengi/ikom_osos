// Meter profiles on the gateway: storage, upload protocol, assignment.
//
// A profile arrives over MQTT as a short series of commands (see
// source/meter-profiles/README.md and tools/meterprofile.py wire_commands):
//
//   profile_begin  -> profile_regs x N -> profile_meta x M -> profile_commit
//
// Each is acked, so the sender waits for ok before the next. Chunks go straight
// to flash and are never held in RAM: an 8 KB profile cannot be assembled in the
// ~25 KB of heap this board has left once TLS is up. The upload lands in
// up.bin/up.js and is renamed over the real files only by a successful commit, so
// a failed or interrupted upload never damages a working profile.
//
// While polling, one profile's registers (<= 48 x 56 B) are held in `regs_`. Polls
// never service MQTT, so no command can arrive mid-poll and replace them.
//
// This header has no Arduino dependency apart from ArduinoJson: the filesystem is
// the OsosFs interface below, LittleFS on the device and a directory on a PC, so
// firmware-esp8266/tests/ runs every rule here against the shared vectors.
#pragma once

#include <ArduinoJson.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "osos_codec.h"

#ifdef ARDUINO
#  include <pgmspace.h>
#else
#  define memcpy_P memcpy
#endif

#define OSOS_MAX_PROFILES   6      /* stored on flash, not counting the built-in */
#define OSOS_MAX_BLOB       8192
#define OSOS_MAX_REQUEST_MS 8000   /* timeout_ms x (retries + 1) */
#define OSOS_MAX_ANALYZERS  8
#define OSOS_AID_LEN        16
#define OSOS_PID_LEN        25
#define OSOS_REGS_PER_CHUNK 8
#define OSOS_PF_DIR         "/pf"

// ---------------------------------------------------------------- filesystem --
class OsosFs {
 public:
  virtual ~OsosFs() {}
  virtual int  size(const char* path) = 0;                  // -1 when missing
  virtual bool write(const char* path, const void* data, size_t n, bool append) = 0;
  virtual int  read(const char* path, size_t off, void* data, size_t n) = 0;  // bytes, -1 on error
  virtual bool remove(const char* path) = 0;
  virtual bool rename(const char* from, const char* to) = 0;  // replaces `to`
  virtual size_t freeBytes() = 0;
  // Calls cb(name) for every file directly inside `dir`.
  virtual void list(const char* dir, void (*cb)(const char* name, void* ctx), void* ctx) = 0;
};

// -------------------------------------------------------------------- result --
struct ProfileResult {
  bool handled = false;           // false: not a profile command, caller dispatches it
  bool ok = false;
  char detail[96] = "";
  bool publish_list = false;      // the `profiles` topic changed
  char changed_profile[OSOS_PID_LEN] = "";   // republish analyzers using this profile
  char changed_analyzer[OSOS_AID_LEN] = "";  // ...and this analyzer
  // profile_test: the caller owns the Modbus connection, so it performs the read.
  bool want_test = false;
  char test_analyzer[OSOS_AID_LEN] = "";
  osos_reg_t test_reg;
  uint8_t test_raw_words = 0;     // > 0: raw dump of that many registers, no decode
};

class ProfileStore {
 public:
  ProfileStore(OsosFs& fs, const osos_builtin_t& builtin) : fs_(fs), builtin_(builtin) {}

  // `ids` must stay valid for the life of the store (the analyzer table).
  void begin(const char* const* ids, uint8_t n) {
    nan_ = n > OSOS_MAX_ANALYZERS ? OSOS_MAX_ANALYZERS : n;
    for (uint8_t i = 0; i < nan_; i++) {
      strncpy(aid_[i], ids[i], OSOS_AID_LEN - 1);
      aid_[i][OSOS_AID_LEN - 1] = 0;
      pid_[i][0] = 0;                       // empty == use the built-in
    }
    loadAssign();
  }

  // ----------------------------------------------------------- reading ----
  // Loads `pid` into the working set (stored profile first, then the built-in).
  bool load(const char* pid) {
    if (cache_ok_ && strcmp(cache_id_, pid) == 0) return true;
    cache_ok_ = false;
    char path[40];
    binPath(path, sizeof path, pid);
    const int sz = fs_.size(path);
    if (sz >= (int)sizeof(osos_pf_header_t)) {
      osos_pf_header_t h;
      if (fs_.read(path, 0, &h, sizeof h) == (int)sizeof h && validHeader(h) &&
          sz == (int)(sizeof h + (size_t)h.n * sizeof(osos_reg_t)) &&
          fs_.read(path, sizeof h, regs_, (size_t)h.n * sizeof(osos_reg_t)) ==
              (int)((size_t)h.n * sizeof(osos_reg_t))) {
        hdr_ = h;
        return remember(pid);
      }
    }
    if (strcmp(pid, builtin_.id) == 0) {
      hdr_ = builtin_.hdr;
      memcpy_P(regs_, builtin_.regs, (size_t)hdr_.n * sizeof(osos_reg_t));
      return remember(pid);
    }
    return false;
  }
  const osos_pf_header_t& header() const { return hdr_; }
  const osos_reg_t* regs() const { return regs_; }
  uint8_t count() const { return hdr_.n; }

  osos_timing_t timing() const {
    osos_timing_t t;
    t.gap_ms = hdr_.gap_ms;
    t.timeout_ms = hdr_.timeout_ms;
    t.max_block = hdr_.max_block;
    t.retries = hdr_.retries;
    return t;
  }

  // The profile an analyzer reads with: its assignment, else the built-in.
  const char* effectiveId(const char* aid) const {
    for (uint8_t i = 0; i < nan_; i++)
      if (strcmp(aid_[i], aid) == 0) return pid_[i][0] ? pid_[i] : builtin_.id;
    return builtin_.id;
  }

  bool exists(const char* pid) {
    char path[40];
    binPath(path, sizeof path, pid);
    return fs_.size(path) >= (int)sizeof(osos_pf_header_t) || strcmp(pid, builtin_.id) == 0;
  }

  // Display metadata (the profile JSON, verbatim) for publishing.
  int blobSize(const char* pid) {
    char path[40];
    if (storedValid(pid)) {
      jsPath(path, sizeof path, pid);
      return fs_.size(path);
    }
    return strcmp(pid, builtin_.id) == 0 ? builtin_.hdr.blob_len : -1;
  }
  int readBlob(const char* pid, size_t off, uint8_t* buf, size_t n) {
    if (storedValid(pid)) {
      char path[40];
      jsPath(path, sizeof path, pid);
      return fs_.read(path, off, buf, n);
    }
    if (strcmp(pid, builtin_.id) != 0 || off >= builtin_.hdr.blob_len) return -1;
    if (off + n > builtin_.hdr.blob_len) n = builtin_.hdr.blob_len - off;
    memcpy_P(buf, builtin_.blob + off, n);
    return (int)n;
  }

  // `{"v":2,"profiles":[...],"assign":{...},"cap":{...}}` for the retained topic.
  size_t listingJson(char* out, size_t n) {
    JsonDocument doc;
    fillListing(doc);
    return serializeJson(doc, out, n);
  }
  void fillListing(JsonDocument& doc) {
    doc["v"] = 2;
    JsonArray arr = doc["profiles"].to<JsonArray>();
    bool shadowed = false;
    ListCtx lc{this, &arr, &shadowed};
    fs_.list(OSOS_PF_DIR, listCb, &lc);
    if (!shadowed) {
      JsonObject o = arr.add<JsonObject>();
      o["id"] = builtin_.id;
      o["rev"] = builtin_.hdr.rev;
      o["n"] = builtin_.hdr.n;
      o["name"] = builtin_.hdr.name;
      o["builtin"] = true;
    }
    JsonObject as = doc["assign"].to<JsonObject>();
    for (uint8_t i = 0; i < nan_; i++) as[aid_[i]] = pid_[i][0] ? pid_[i] : builtin_.id;
    JsonObject cap = doc["cap"].to<JsonObject>();
    cap["regs"] = OSOS_MAX_REGS;
    cap["profiles"] = OSOS_MAX_PROFILES;
    cap["blob"] = OSOS_MAX_BLOB;
    cap["free"] = (uint32_t)fs_.freeBytes();
  }

  // ---------------------------------------------------------- commands ----
  ProfileResult handle(const char* action, JsonVariantConst a) {
    ProfileResult r;
    r.handled = true;
    if (strcmp(action, "profile_begin") == 0) return cmdBegin(a, r);
    if (strcmp(action, "profile_regs") == 0) return cmdRegs(a, r);
    if (strcmp(action, "profile_meta") == 0) return cmdMeta(a, r);
    if (strcmp(action, "profile_commit") == 0) return cmdCommit(a, r);
    if (strcmp(action, "profile_delete") == 0) return cmdDelete(a, r);
    if (strcmp(action, "profile_assign") == 0) return cmdAssign(a, r);
    if (strcmp(action, "profile_list") == 0) return cmdList(r);
    if (strcmp(action, "profile_test") == 0) return cmdTest(a, r);
    r.handled = false;
    return r;
  }

  // Text for the ack of a profile_test once the caller has done the read.
  static void describeTest(const ProfileResult& r, const uint16_t* w, uint8_t n,
                           char* out, size_t outn) {
    size_t pos = (size_t)snprintf(out, outn, "raw=");
    for (uint8_t i = 0; i < n && pos + 6 < outn; i++)
      pos += (size_t)snprintf(out + pos, outn - pos, i ? " %04X" : "%04X", w[i]);
    if (r.test_raw_words) return;
    double v;
    char num[32];
    if (osos_decode(&r.test_reg, w, &v)) {
      osos_format(v, r.test_reg.decimals, num, sizeof num);
      snprintf(out + pos, outn - pos, " value=%s", num);
    } else {
      snprintf(out + pos, outn - pos, " value=n/a (not finite)");
    }
  }

 private:
  struct Upload {
    bool active = false;
    char id[OSOS_PID_LEN] = "";
    osos_pf_header_t hdr;
    uint8_t got = 0;
    uint16_t blob_got = 0;
  };

  OsosFs& fs_;
  const osos_builtin_t& builtin_;
  osos_pf_header_t hdr_;
  osos_reg_t regs_[OSOS_MAX_REGS];
  char cache_id_[OSOS_PID_LEN] = "";
  bool cache_ok_ = false;
  char aid_[OSOS_MAX_ANALYZERS][OSOS_AID_LEN];
  char pid_[OSOS_MAX_ANALYZERS][OSOS_PID_LEN];
  uint8_t nan_ = 0;
  Upload up_;

  // ---- paths
  static void binPath(char* o, size_t n, const char* pid) { snprintf(o, n, OSOS_PF_DIR "/%s.bin", pid); }
  static void jsPath(char* o, size_t n, const char* pid) { snprintf(o, n, OSOS_PF_DIR "/%s.js", pid); }

  static bool validId(const char* s) {
    if (!s) return false;
    const size_t n = strlen(s);
    if (n < 1 || n > 24) return false;
    for (size_t i = 0; i < n; i++) {
      const char c = s[i];
      const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                      (i > 0 && (c == '_' || c == '-'));
      if (!ok) return false;
    }
    return true;
  }
  static bool validKey(const char* s) {
    if (!s) return false;
    const size_t n = strlen(s);
    if (n < 1 || n > 31) return false;
    for (size_t i = 0; i < n; i++) {
      const char c = s[i];
      if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_'))
        return false;
    }
    return true;
  }
  static bool validHeader(const osos_pf_header_t& h) {
    return memcmp(h.magic, OSOS_PF_MAGIC, 4) == 0 && h.ver == OSOS_PF_VER && h.n >= 1 &&
           h.n <= OSOS_MAX_REGS;
  }

  bool remember(const char* pid) {
    strncpy(cache_id_, pid, sizeof cache_id_ - 1);
    cache_id_[sizeof cache_id_ - 1] = 0;
    cache_ok_ = true;
    return true;
  }
  void invalidate() { cache_ok_ = false; }

  // A stored profile whose metadata file matches its header. After a power cut
  // between the two renames of a commit they can disagree; then the metadata is
  // ignored rather than shown against the wrong registers.
  bool storedValid(const char* pid) {
    char path[40];
    binPath(path, sizeof path, pid);
    osos_pf_header_t h;
    if (fs_.size(path) < (int)sizeof h || fs_.read(path, 0, &h, sizeof h) != (int)sizeof h ||
        !validHeader(h))
      return false;
    jsPath(path, sizeof path, pid);
    return fs_.size(path) == (int)h.blob_len;
  }

  // ---- stored profile enumeration
  struct ListCtx { ProfileStore* self; JsonArray* arr; bool* shadowed; };
  static bool endsWith(const char* s, const char* suffix) {
    const size_t a = strlen(s), b = strlen(suffix);
    return a >= b && strcmp(s + a - b, suffix) == 0;
  }
  static void listCb(const char* name, void* ctx) {
    ListCtx* lc = static_cast<ListCtx*>(ctx);
    if (!endsWith(name, ".bin") || strcmp(name, "up.bin") == 0) return;
    char pid[OSOS_PID_LEN];
    const size_t n = strlen(name) - 4;
    if (n < 1 || n >= sizeof pid) return;
    memcpy(pid, name, n);
    pid[n] = 0;
    char path[40];
    binPath(path, sizeof path, pid);
    osos_pf_header_t h;
    if (lc->self->fs_.size(path) < (int)sizeof h ||
        lc->self->fs_.read(path, 0, &h, sizeof h) != (int)sizeof h || !validHeader(h))
      return;
    h.name[sizeof h.name - 1] = 0;
    JsonObject o = lc->arr->add<JsonObject>();
    o["id"] = pid;                 // ArduinoJson copies: pid is a stack buffer
    o["rev"] = h.rev;
    o["n"] = h.n;
    o["name"] = h.name;
    if (strcmp(pid, lc->self->builtin_.id) == 0) *lc->shadowed = true;
  }
  struct CountCtx { int n; const char* skip; bool found; };
  static void countCb(const char* name, void* ctx) {
    CountCtx* c = static_cast<CountCtx*>(ctx);
    if (!endsWith(name, ".bin") || strcmp(name, "up.bin") == 0) return;
    c->n++;
    char want[40];
    snprintf(want, sizeof want, "%s.bin", c->skip);
    if (strcmp(name, want) == 0) c->found = true;
  }

  // ---- assignment persistence: /pf/assign.js = {"an-01":"sdm630"}
  void loadAssign() {
    char buf[384];
    const int sz = fs_.size(OSOS_PF_DIR "/assign.js");
    if (sz <= 0 || sz >= (int)sizeof buf) return;
    const int got = fs_.read(OSOS_PF_DIR "/assign.js", 0, buf, sizeof buf - 1);
    if (got <= 0) return;
    buf[got] = 0;
    JsonDocument doc;
    if (deserializeJson(doc, buf)) return;
    for (uint8_t i = 0; i < nan_; i++) {
      const char* p = doc[aid_[i]] | "";
      if (validId(p)) { strncpy(pid_[i], p, OSOS_PID_LEN - 1); pid_[i][OSOS_PID_LEN - 1] = 0; }
    }
  }
  bool saveAssign() {
    JsonDocument doc;
    for (uint8_t i = 0; i < nan_; i++)
      if (pid_[i][0]) doc[aid_[i]] = pid_[i];
    char buf[384];
    const size_t n = serializeJson(doc, buf, sizeof buf);
    if (n >= sizeof buf - 1) return false;
    return fs_.write(OSOS_PF_DIR "/assign.js", buf, n, false);
  }

  // ---- commands
  ProfileResult cmdBegin(JsonVariantConst a, ProfileResult& r) {
    up_.active = false;
    fs_.remove(OSOS_PF_DIR "/up.bin");
    fs_.remove(OSOS_PF_DIR "/up.js");

    const char* id = a["id"] | "";
    if (!validId(id)) { snprintf(r.detail, sizeof r.detail, "bad profile id"); return r; }

    const int n = intArg(a["n"], -1), bl = intArg(a["blob_len"], -1);
    if (n < 1 || n > OSOS_MAX_REGS) {
      snprintf(r.detail, sizeof r.detail, "n out of range 1..%d", OSOS_MAX_REGS);
      return r;
    }
    if (bl < 2 || bl > OSOS_MAX_BLOB) {
      snprintf(r.detail, sizeof r.detail, "blob_len out of range 2..%d", OSOS_MAX_BLOB);
      return r;
    }
    osos_pf_header_t h;
    memset(&h, 0, sizeof h);
    memcpy(h.magic, OSOS_PF_MAGIC, 4);
    h.ver = OSOS_PF_VER;
    h.n = (uint8_t)n;
    h.blob_len = (uint16_t)bl;
    int v;
    if (!rangeArg(a["rev"], 1, 0, 65535, &v)) { snprintf(r.detail, sizeof r.detail, "rev out of range 0..65535"); return r; }
    h.rev = (uint16_t)v;
    if (!rangeArg(a["gap"], 30, 0, 2000, &v)) { snprintf(r.detail, sizeof r.detail, "gap out of range 0..2000"); return r; }
    h.gap_ms = (uint16_t)v;
    if (!rangeArg(a["tmo"], 500, 50, 5000, &v)) { snprintf(r.detail, sizeof r.detail, "tmo out of range 50..5000"); return r; }
    h.timeout_ms = (uint16_t)v;
    if (!rangeArg(a["blk"], 1, 1, 64, &v)) { snprintf(r.detail, sizeof r.detail, "blk out of range 1..64"); return r; }
    h.max_block = (uint8_t)v;
    if (!rangeArg(a["retries"], 0, 0, 3, &v)) { snprintf(r.detail, sizeof r.detail, "retries out of range 0..3"); return r; }
    h.retries = (uint8_t)v;
    if ((int)h.timeout_ms * ((int)h.retries + 1) > OSOS_MAX_REQUEST_MS) {
      snprintf(r.detail, sizeof r.detail, "timeout x attempts exceeds %d ms", OSOS_MAX_REQUEST_MS);
      return r;
    }
    const char* name = a["name"] | "";
    if (strlen(name) > 44) { snprintf(r.detail, sizeof r.detail, "name too long"); return r; }
    strncpy(h.name, name, sizeof h.name - 1);

    CountCtx cc{0, id, false};
    fs_.list(OSOS_PF_DIR, countCb, &cc);
    if (!cc.found && cc.n >= OSOS_MAX_PROFILES) {
      snprintf(r.detail, sizeof r.detail, "profile store full (%d); delete one first", OSOS_MAX_PROFILES);
      return r;
    }
    const size_t need = sizeof h + (size_t)n * sizeof(osos_reg_t) + (size_t)bl + 3072;
    if (fs_.freeBytes() < need) { snprintf(r.detail, sizeof r.detail, "flash full"); return r; }
    if (!fs_.write(OSOS_PF_DIR "/up.bin", &h, sizeof h, false)) {
      snprintf(r.detail, sizeof r.detail, "flash write failed");
      return r;
    }
    up_ = Upload();
    up_.active = true;
    strncpy(up_.id, id, sizeof up_.id - 1);
    up_.hdr = h;
    r.ok = true;
    snprintf(r.detail, sizeof r.detail, "upload %s started", id);
    return r;
  }

  bool mine(JsonVariantConst a) {
    const char* id = a["id"] | "";
    return up_.active && strcmp(id, up_.id) == 0;
  }

  ProfileResult cmdRegs(JsonVariantConst a, ProfileResult& r) {
    if (!mine(a)) { snprintf(r.detail, sizeof r.detail, "no upload in progress for that id"); return r; }
    if (intArg(a["i"], -1) != (int)up_.got) {
      snprintf(r.detail, sizeof r.detail, "out of order, expected index %u", up_.got);
      return r;
    }
    JsonArrayConst arr = a["regs"].as<JsonArrayConst>();
    const size_t cnt = arr.size();
    if (cnt < 1 || cnt > OSOS_REGS_PER_CHUNK) {
      snprintf(r.detail, sizeof r.detail, "regs must hold 1..%d entries", OSOS_REGS_PER_CHUNK);
      return r;
    }
    if (up_.got + cnt > up_.hdr.n) { snprintf(r.detail, sizeof r.detail, "more registers than declared"); return r; }
    osos_reg_t tmp[OSOS_REGS_PER_CHUNK];
    size_t i = 0;
    for (JsonVariantConst e : arr) {
      const char* why = parseWireReg(e, &tmp[i]);
      if (why) { snprintf(r.detail, sizeof r.detail, "reg %u: %s", (unsigned)(up_.got + i), why); return r; }
      i++;
    }
    if (!fs_.write(OSOS_PF_DIR "/up.bin", tmp, cnt * sizeof(osos_reg_t), true)) {
      snprintf(r.detail, sizeof r.detail, "flash write failed");
      return r;
    }
    up_.got += (uint8_t)cnt;
    r.ok = true;
    snprintf(r.detail, sizeof r.detail, "%u/%u regs", up_.got, up_.hdr.n);
    return r;
  }

  ProfileResult cmdMeta(JsonVariantConst a, ProfileResult& r) {
    if (!mine(a)) { snprintf(r.detail, sizeof r.detail, "no upload in progress for that id"); return r; }
    if (intArg(a["off"], -1) != (int)up_.blob_got) {
      snprintf(r.detail, sizeof r.detail, "out of order, expected offset %u", up_.blob_got);
      return r;
    }
    const char* data = a["data"] | "";
    const size_t len = strlen(data);
    if (len == 0) { snprintf(r.detail, sizeof r.detail, "data must be a non-empty string"); return r; }
    if (up_.blob_got + len > up_.hdr.blob_len) { snprintf(r.detail, sizeof r.detail, "more metadata than declared"); return r; }
    if (!fs_.write(OSOS_PF_DIR "/up.js", data, len, up_.blob_got > 0)) {
      snprintf(r.detail, sizeof r.detail, "flash write failed");
      return r;
    }
    up_.blob_got += (uint16_t)len;
    r.ok = true;
    snprintf(r.detail, sizeof r.detail, "%u/%u bytes", up_.blob_got, up_.hdr.blob_len);
    return r;
  }

  ProfileResult cmdCommit(JsonVariantConst a, ProfileResult& r) {
    if (!mine(a)) { snprintf(r.detail, sizeof r.detail, "no upload in progress for that id"); return r; }
    if (up_.got != up_.hdr.n) {
      snprintf(r.detail, sizeof r.detail, "incomplete: %u/%u regs", up_.got, up_.hdr.n);
      return r;
    }
    if (up_.blob_got != up_.hdr.blob_len) {
      snprintf(r.detail, sizeof r.detail, "incomplete: %u/%u bytes", up_.blob_got, up_.hdr.blob_len);
      return r;
    }
    // Duplicate keys, checked on what actually reached flash.
    invalidate();
    const size_t total = (size_t)up_.hdr.n * sizeof(osos_reg_t);
    if (fs_.read(OSOS_PF_DIR "/up.bin", sizeof(osos_pf_header_t), regs_, total) != (int)total) {
      snprintf(r.detail, sizeof r.detail, "flash read failed");
      return r;
    }
    for (uint8_t i = 0; i < up_.hdr.n; i++)
      for (uint8_t j = (uint8_t)(i + 1); j < up_.hdr.n; j++)
        if (strcmp(regs_[i].key, regs_[j].key) == 0) {
          snprintf(r.detail, sizeof r.detail, "duplicate register key");
          return r;
        }
    char first = 0, last = 0;
    fs_.read(OSOS_PF_DIR "/up.js", 0, &first, 1);
    fs_.read(OSOS_PF_DIR "/up.js", up_.hdr.blob_len - 1, &last, 1);
    if (first != '{' || last != '}') {
      snprintf(r.detail, sizeof r.detail, "metadata is not a JSON object");
      return r;
    }
    char bin[40], js[40];
    binPath(bin, sizeof bin, up_.id);
    jsPath(js, sizeof js, up_.id);
    // Metadata first: if power fails between the renames the sizes disagree and
    // storedValid() ignores the metadata instead of showing the wrong labels.
    if (!fs_.rename(OSOS_PF_DIR "/up.js", js) || !fs_.rename(OSOS_PF_DIR "/up.bin", bin)) {
      snprintf(r.detail, sizeof r.detail, "flash rename failed");
      return r;
    }
    up_.active = false;
    r.ok = true;
    r.publish_list = true;
    strncpy(r.changed_profile, up_.id, sizeof r.changed_profile - 1);
    snprintf(r.detail, sizeof r.detail, "stored %s rev %u (%u regs)", up_.id, up_.hdr.rev, up_.hdr.n);
    return r;
  }

  ProfileResult cmdDelete(JsonVariantConst a, ProfileResult& r) {
    const char* id = a["id"] | "";
    char bin[40];
    if (!validId(id)) { snprintf(r.detail, sizeof r.detail, "no such stored profile"); return r; }
    binPath(bin, sizeof bin, id);
    if (fs_.size(bin) < 0) { snprintf(r.detail, sizeof r.detail, "no such stored profile"); return r; }
    char users[64] = "";
    for (uint8_t i = 0; i < nan_; i++) {
      if (strcmp(pid_[i], id) == 0) {
        if (users[0]) strncat(users, ", ", sizeof users - strlen(users) - 1);
        strncat(users, aid_[i], sizeof users - strlen(users) - 1);
      }
    }
    if (users[0]) { snprintf(r.detail, sizeof r.detail, "in use by %s", users); return r; }
    char js[40];
    jsPath(js, sizeof js, id);
    fs_.remove(bin);
    fs_.remove(js);
    invalidate();
    r.ok = true;
    r.publish_list = true;
    strncpy(r.changed_profile, id, sizeof r.changed_profile - 1);   // built-in may take over
    snprintf(r.detail, sizeof r.detail, "deleted %s", id);
    return r;
  }

  ProfileResult cmdAssign(JsonVariantConst a, ProfileResult& r) {
    const char* aid = a["analyzer"] | "";
    const char* pid = a["profile"] | "";
    int idx = -1;
    for (uint8_t i = 0; i < nan_; i++) if (strcmp(aid_[i], aid) == 0) idx = i;
    if (idx < 0) { snprintf(r.detail, sizeof r.detail, "no such analyzer: %.24s", aid); return r; }
    if (!validId(pid) || !exists(pid)) { snprintf(r.detail, sizeof r.detail, "no such profile: %.24s", pid); return r; }
    char old[OSOS_PID_LEN];
    strncpy(old, pid_[idx], sizeof old);
    strncpy(pid_[idx], pid, OSOS_PID_LEN - 1);
    pid_[idx][OSOS_PID_LEN - 1] = 0;
    if (!saveAssign()) {
      strncpy(pid_[idx], old, OSOS_PID_LEN);
      snprintf(r.detail, sizeof r.detail, "could not save assignment");
      return r;
    }
    r.ok = true;
    r.publish_list = true;
    strncpy(r.changed_analyzer, aid, sizeof r.changed_analyzer - 1);
    snprintf(r.detail, sizeof r.detail, "%s reads as %s", aid, pid);
    return r;
  }

  ProfileResult cmdList(ProfileResult& r) {
    r.ok = true;
    r.publish_list = true;
    snprintf(r.detail, sizeof r.detail, "listing republished");
    return r;
  }

  ProfileResult cmdTest(JsonVariantConst a, ProfileResult& r) {
    const char* aid = a["analyzer"] | "";
    bool known = false;
    for (uint8_t i = 0; i < nan_; i++) if (strcmp(aid_[i], aid) == 0) known = true;
    if (!known) { snprintf(r.detail, sizeof r.detail, "no such analyzer: %.24s", aid); return r; }
    const int addr = intArg(a["address"], -1);
    if (addr < 0 || addr > 65535) { snprintf(r.detail, sizeof r.detail, "address out of range"); return r; }
    const int fc = intArg(a["fc"], 3);
    if (fc != 3 && fc != 4) { snprintf(r.detail, sizeof r.detail, "fc must be 3 or 4"); return r; }
    strncpy(r.test_analyzer, aid, sizeof r.test_analyzer - 1);
    memset(&r.test_reg, 0, sizeof r.test_reg);
    r.test_reg.address = (uint16_t)addr;
    r.test_reg.fc = (uint8_t)fc;
    r.test_reg.scale = 1;
    const int count = intArg(a["count"], 0);
    if (count != 0) {
      if (count < 1 || count > 8 || addr + count > 65536) {
        snprintf(r.detail, sizeof r.detail, "count must be 1..8 within the address space");
        return r;
      }
      r.test_raw_words = (uint8_t)count;
    } else {
      JsonObjectConst o = a.as<JsonObjectConst>();
      osos_reg_t t;
      JsonDocument wire;                   // reuse the register parser
      wire["k"] = "T";
      wire["a"] = addr;
      wire["f"] = fc;
      wire["t"] = o["type"] | "f32";
      wire["w"] = o["word_order"] | "big";
      wire["b"] = o["byte_order"] | "big";
      wire["s"] = o["scale"].is<double>() ? o["scale"].as<double>() : 1.0;
      wire["o"] = o["offset"].is<double>() ? o["offset"].as<double>() : 0.0;
      wire["d"] = intArg(o["decimals"], 3);
      const char* why = parseWireReg(wire.as<JsonVariantConst>(), &t);
      if (why) { snprintf(r.detail, sizeof r.detail, "%s", why); return r; }
      r.test_reg = t;
    }
    r.ok = true;
    r.want_test = true;
    snprintf(r.detail, sizeof r.detail, "testing");
    return r;
  }

  // ---- argument helpers
  static int intArg(JsonVariantConst v, int dflt) {
    if (v.isNull()) return dflt;
    return v.is<int>() ? v.as<int>() : -2147483647;   // present but not an integer: fails every range
  }
  static bool rangeArg(JsonVariantConst v, int dflt, int lo, int hi, int* out) {
    const int x = intArg(v, dflt);
    if (x < lo || x > hi) return false;
    *out = x;
    return true;
  }

  // One register in wire form {k,a,f,t,w,b,s,o,d} -> binary record. Returns the
  // reason it was refused, or nullptr.
  static const char* parseWireReg(JsonVariantConst e, osos_reg_t* out) {
    memset(out, 0, sizeof *out);
    const char* k = e["k"] | "";
    if (!validKey(k)) return "bad key";
    const int t = osos_type_from_name(e["t"] | "");
    if (t < 0) return "bad type";
    const int a = intArg(e["a"], -1);
    if (a < 0 || a + osos_type_words((uint8_t)t) > 65536) return "address out of range";
    const int f = intArg(e["f"], -1);
    if (f != 3 && f != 4) return "fc must be 3 or 4";
    const char* w = e["w"] | "";
    const char* b = e["b"] | "";
    if ((strcmp(w, "big") && strcmp(w, "little")) || (strcmp(b, "big") && strcmp(b, "little")))
      return "bad word/byte order";
    if (!e["s"].is<double>() || !e["o"].is<double>() || e["s"].as<double>() == 0)
      return "bad scale/offset";
    const int d = intArg(e["d"], -1);
    if (d < 0 || d > 6) return "decimals out of range";
    strncpy(out->key, k, sizeof out->key - 1);
    out->scale = e["s"].as<double>();
    out->offset = e["o"].as<double>();
    out->address = (uint16_t)a;
    out->fc = (uint8_t)f;
    out->type = (uint8_t)t;
    out->order = (uint8_t)((strcmp(w, "little") == 0 ? OSOS_ORDER_WORD_LITTLE : 0) |
                           (strcmp(b, "little") == 0 ? OSOS_ORDER_BYTE_LITTLE : 0));
    out->decimals = (uint8_t)d;
    return nullptr;
  }
};
