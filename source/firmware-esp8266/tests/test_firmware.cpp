// Host tests for osos_codec.h and profile_store.h.
//
// Runs the shared vectors (source/meter-profiles/vectors.json) through the real
// firmware code: decoding, request planning, polling, and the whole upload
// protocol including its refusals. The Python (tests/test_meterprofile.py) and
// JavaScript (browser-hmi/meter-map/tests) suites run the same file.
#include <ArduinoJson.h>

#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "host_fs.h"
#include "osos_builtin_dkm440.h"
#include "osos_codec.h"
#include "profile_store.h"

static int g_checks = 0, g_failed = 0;
#define CHECK(cond)                                                          \
  do {                                                                       \
    g_checks++;                                                              \
    if (!(cond)) {                                                           \
      g_failed++;                                                            \
      std::printf("  FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);          \
    }                                                                        \
  } while (0)
#define CHECK_MSG(cond, ...)                                                 \
  do {                                                                       \
    g_checks++;                                                              \
    if (!(cond)) {                                                           \
      g_failed++;                                                            \
      std::printf("  FAIL %s:%d  %s  ", __FILE__, __LINE__, #cond);          \
      std::printf(__VA_ARGS__);                                              \
      std::printf("\n");                                                     \
    }                                                                        \
  } while (0)

static JsonDocument VEC;

static void loadVectors() {
  const char* path = "../../meter-profiles/vectors.json";
  std::ifstream f(path);
  std::stringstream ss;
  ss << f.rdbuf();
  const DeserializationError e = deserializeJson(VEC, ss.str());
  if (e) { std::printf("cannot load %s: %s\n", path, e.c_str()); std::exit(2); }
}

static const char* TMP = "/tmp/osos_fw_test_fs";

// ---------------------------------------------------------------- helpers ----
static osos_reg_t mkReg(const char* type, const char* word, const char* byte, double s, double o) {
  osos_reg_t r;
  memset(&r, 0, sizeof r);
  strcpy(r.key, "T");
  r.type = (uint8_t)osos_type_from_name(type);
  r.order = (uint8_t)((strcmp(word, "little") == 0 ? OSOS_ORDER_WORD_LITTLE : 0) |
                      (strcmp(byte, "little") == 0 ? OSOS_ORDER_BYTE_LITTLE : 0));
  r.scale = s;
  r.offset = o;
  r.fc = 3;
  return r;
}

static ProfileResult run(ProfileStore& s, const char* action, const char* json) {
  JsonDocument d;
  deserializeJson(d, json);
  return s.handle(action, d.as<JsonVariantConst>());
}

static ProfileResult runVec(ProfileStore& s, JsonObjectConst cmd) {
  return s.handle(cmd["action"].as<const char*>(), cmd["args"]);
}

static std::string beginJson(const char* id = "x1", int n = 1, int bl = 2, int gap = 30,
                             int tmo = 500, int blk = 1, int retries = 0, int rev = 1) {
  char b[256];
  snprintf(b, sizeof b,
           "{\"id\":\"%s\",\"name\":\"T\",\"rev\":%d,\"n\":%d,\"blob_len\":%d,\"gap\":%d,"
           "\"tmo\":%d,\"blk\":%d,\"retries\":%d}",
           id, rev, n, bl, gap, tmo, blk, retries);
  return b;
}

static const char* GOOD_REG =
    "{\"k\":\"A\",\"a\":0,\"f\":3,\"t\":\"u16\",\"w\":\"big\",\"b\":\"big\",\"s\":1,\"o\":0,\"d\":0}";

static std::string regsJson(const char* id, int i, const std::string& reg) {
  return std::string("{\"id\":\"") + id + "\",\"i\":" + std::to_string(i) + ",\"regs\":[" + reg + "]}";
}

static std::string wireReg(const char* tweakKey, const char* tweakVal) {
  // GOOD_REG with one member replaced by raw JSON text
  JsonDocument d;
  deserializeJson(d, GOOD_REG);
  JsonDocument v;
  deserializeJson(v, tweakVal);
  d[tweakKey] = v.as<JsonVariant>();
  std::string out;
  serializeJson(d, out);
  return out;
}

static std::vector<uint8_t> readAll(HostFs& fs, const char* path) {
  std::vector<uint8_t> v(fs.size(path) > 0 ? fs.size(path) : 0);
  if (!v.empty()) fs.read(path, 0, v.data(), v.size());
  return v;
}

static std::string hex(const uint8_t* p, size_t n) {
  std::string s;
  char b[3];
  for (size_t i = 0; i < n; i++) { snprintf(b, sizeof b, "%02x", p[i]); s += b; }
  return s;
}

static const char* kAnalyzers[] = {"an-01", "an-02"};

struct Rig {
  HostFs fs;
  ProfileStore store;
  Rig() : fs(TMP), store(fs, kBuiltin) { store.begin(kAnalyzers, 2); }
};

static bool uploadWire(ProfileStore& s, const char* name) {
  JsonArrayConst cmds = VEC["wire"][name]["commands"].as<JsonArrayConst>();
  bool all = true;
  for (JsonObjectConst c : cmds) {
    ProfileResult r = runVec(s, c);
    if (!r.ok) { std::printf("    %s: %s\n", c["action"].as<const char*>(), r.detail); all = false; }
  }
  return all;
}

// ------------------------------------------------------------------ tests ----
static void testDecode() {
  std::printf("decode vectors\n");
  for (JsonObjectConst c : VEC["decode"].as<JsonArrayConst>()) {
    osos_reg_t r = mkReg(c["type"], c["word_order"], c["byte_order"], c["scale"], c["offset"]);
    uint16_t w[4] = {0};
    int n = 0;
    for (JsonVariantConst x : c["words"].as<JsonArrayConst>()) w[n++] = x.as<uint16_t>();
    double got = 0;
    const bool ok = osos_decode(&r, w, &got);
    const char* name = c["name"];
    if (c["expect"].isNull()) {
      CHECK_MSG(!ok, "%s should be a failed read", name);
    } else {
      const double want = c["expect"];
      const double tol = 1e-9 * (want < 0 ? -want : want) + 1e-9;
      CHECK_MSG(ok && got >= want - tol && got <= want + tol, "%s: got %.12g want %.12g", name, got, want);
    }
  }
}

static void testPlan() {
  std::printf("plan vectors\n");
  for (JsonObjectConst c : VEC["plan"].as<JsonArrayConst>()) {
    std::vector<osos_reg_t> regs;
    for (JsonObjectConst r : c["regs"].as<JsonArrayConst>()) {
      osos_reg_t x = mkReg(r["type"], "big", "big", 1, 0);
      x.address = r["address"];
      x.fc = r["fc"];
      regs.push_back(x);
    }
    uint8_t order[OSOS_MAX_REGS];
    osos_block_t blocks[OSOS_MAX_REGS];
    const int nb = osos_plan(regs.data(), (int)regs.size(), c["max_block"], order, blocks);
    JsonArrayConst want = c["blocks"].as<JsonArrayConst>();
    const char* name = c["name"];
    CHECK_MSG(nb == (int)want.size(), "%s: %d blocks, want %d", name, nb, (int)want.size());
    int bi = 0;
    for (JsonArrayConst w : want) {
      if (bi >= nb) break;
      const osos_block_t& b = blocks[bi++];
      CHECK_MSG(b.fc == w[0].as<int>() && b.start == w[1].as<int>() && b.words == w[2].as<int>() &&
                    b.count == (int)w[3].as<JsonArrayConst>().size(),
                "%s block %d", name, bi);
      int k = 0;
      for (JsonVariantConst idx : w[3].as<JsonArrayConst>())
        CHECK_MSG(order[b.first + k++] == idx.as<int>(), "%s block %d member", name, bi);
    }
  }
}

struct MemIo {
  std::map<int, uint16_t> mem;
  int fc = 3;
  std::vector<std::vector<int>> log;
};
static bool memRead(void* ctx, uint8_t fc, uint16_t start, uint16_t words, uint16_t* out) {
  MemIo* m = static_cast<MemIo*>(ctx);
  m->log.push_back({fc, start, words});
  if (fc != m->fc) return false;
  for (int i = 0; i < words; i++) {
    auto it = m->mem.find(start + i);
    if (it == m->mem.end()) return false;
    out[i] = it->second;
  }
  return true;
}
static bool memIdle(void*, uint16_t) { return true; }

static const char* wireNameFor(const char* file) {
  if (strstr(file, "sdm630")) return "sdm630";
  if (strstr(file, "generic-int")) return "generic-int";
  return "dkm440";
}

static void testPoll() {
  std::printf("poll vectors (profile uploaded over the wire, then polled)\n");
  for (JsonObjectConst c : VEC["poll"].as<JsonArrayConst>()) {
    Rig rig;
    const char* name = c["name"];
    const char* wn = wireNameFor(c["profile"]);
    CHECK_MSG(uploadWire(rig.store, wn), "%s: upload", name);
    CHECK_MSG(rig.store.load(wn), "%s: load", name);

    MemIo io;
    io.fc = c["fc"];
    for (JsonPairConst kv : c["mem"].as<JsonObjectConst>()) io.mem[atoi(kv.key().c_str())] = kv.value().as<uint16_t>();
    osos_io_t cb = {memRead, memIdle, &io};
    osos_timing_t t = rig.store.timing();
    static osos_poll_result_t res;
    osos_poll(rig.store.regs(), rig.store.count(), &t, &cb, &res);

    CHECK_MSG(res.ok_count == c["ok"].as<int>(), "%s: ok %d want %d", name, res.ok_count, c["ok"].as<int>());
    CHECK_MSG(res.gave_up == c["gave_up"].as<bool>(), "%s: gave_up", name);
    if (c["reads"].is<JsonArrayConst>()) {
      JsonArrayConst want = c["reads"].as<JsonArrayConst>();
      CHECK_MSG(io.log.size() == want.size(), "%s: %d reads, want %d", name, (int)io.log.size(), (int)want.size());
      size_t i = 0;
      for (JsonArrayConst w : want) {
        if (i >= io.log.size()) break;
        CHECK_MSG(io.log[i][0] == w[0].as<int>() && io.log[i][1] == w[1].as<int>() && io.log[i][2] == w[2].as<int>(),
                  "%s: read %d", name, (int)i);
        i++;
      }
    }
    if (c["read_count"].is<int>())
      CHECK_MSG((int)io.log.size() == c["read_count"].as<int>(), "%s: %d reads", name, (int)io.log.size());

    auto fmt = [&](int i) {
      static char b[48];
      if (!res.ok[i]) return (const char*)nullptr;
      osos_format(res.value[i], rig.store.regs()[i].decimals, b, sizeof b);
      return (const char*)b;
    };
    auto check = [&](JsonObjectConst vals, bool all) {
      for (JsonPairConst kv : vals) {
        int idx = -1;
        for (int i = 0; i < rig.store.count(); i++)
          if (strcmp(rig.store.regs()[i].key, kv.key().c_str()) == 0) idx = i;
        CHECK_MSG(idx >= 0, "%s: key %s", name, kv.key().c_str());
        if (idx < 0) continue;
        const char* got = fmt(idx);
        if (kv.value().isNull()) CHECK_MSG(got == nullptr, "%s: %s should be null", name, kv.key().c_str());
        else CHECK_MSG(got && strcmp(got, kv.value().as<const char*>()) == 0, "%s: %s = %s want %s",
                       name, kv.key().c_str(), got ? got : "null", kv.value().as<const char*>());
      }
      if (all) CHECK_MSG((int)vals.size() == rig.store.count(), "%s: key count", name);
    };
    if (c["values"].is<JsonObjectConst>()) check(c["values"].as<JsonObjectConst>(), true);
    if (c["values_subset"].is<JsonObjectConst>()) check(c["values_subset"].as<JsonObjectConst>(), false);
  }
}

static void testWireAndRecords() {
  std::printf("wire upload + stored records\n");
  for (const char* wn : {"dkm440", "sdm630", "generic-int"}) {
    Rig rig;
    CHECK_MSG(uploadWire(rig.store, wn), "%s upload", wn);
    char path[64];
    snprintf(path, sizeof path, "/pf/%s.bin", wn);
    std::vector<uint8_t> bin = readAll(rig.fs, path);
    CHECK(bin.size() > sizeof(osos_pf_header_t));
    CHECK(memcmp(bin.data(), "OSPF", 4) == 0);
    // the records the vectors pin down, byte for byte
    for (JsonObjectConst rec : VEC["records"].as<JsonArrayConst>()) {
      if (strcmp(wireNameFor(rec["file"]), wn) != 0) continue;
      const size_t off = sizeof(osos_pf_header_t) + (size_t)rec["index"].as<int>() * sizeof(osos_reg_t);
      CHECK_MSG(off + sizeof(osos_reg_t) <= bin.size(), "%s record %d in range", wn, rec["index"].as<int>());
      if (off + sizeof(osos_reg_t) <= bin.size())
        CHECK_MSG(hex(bin.data() + off, sizeof(osos_reg_t)) == rec["hex"].as<std::string>(),
                  "%s record %d bytes", wn, rec["index"].as<int>());
    }
    // metadata comes back verbatim
    int bl = rig.store.blobSize(wn);
    CHECK_MSG(bl > 0, "%s blob size", wn);
    std::string blob(bl, 0);
    CHECK(rig.store.readBlob(wn, 0, (uint8_t*)&blob[0], bl) == bl);
    JsonDocument prof;
    CHECK_MSG(!deserializeJson(prof, blob), "%s blob parses", wn);
    CHECK_MSG(strcmp(prof["id"] | "", wn) == 0, "%s blob id", wn);
  }
}

static void testBuiltin() {
  std::printf("built-in DKM-440\n");
  Rig rig;
  CHECK(rig.store.load("dkm440"));
  CHECK(rig.store.count() == 22);
  CHECK(strcmp(rig.store.regs()[0].key, "Supply_Voltage") == 0 && rig.store.regs()[0].address == 260);
  CHECK(strcmp(rig.store.regs()[21].key, "MainBus_TanPhi_L3") == 0 && rig.store.regs()[21].address == 434);
  CHECK(rig.store.timing().gap_ms == 30 && rig.store.timing().max_block == 1 && rig.store.timing().retries == 0);
  for (JsonObjectConst rec : VEC["records"].as<JsonArrayConst>()) {
    if (strcmp(rec["file"], "dkm440.json") != 0) continue;
    CHECK_MSG(hex((const uint8_t*)&rig.store.regs()[rec["index"].as<int>()], sizeof(osos_reg_t)) ==
                  rec["hex"].as<std::string>(), "builtin record %d", rec["index"].as<int>());
  }
  CHECK(rig.store.blobSize("dkm440") == 3087);
  char head[32] = {0};
  CHECK(rig.store.readBlob("dkm440", 0, (uint8_t*)head, 26) == 26);
  CHECK(strncmp(head, "{\"schema\":1,\"id\":\"dkm440\"", 25) == 0);
  CHECK(rig.store.blobSize("nope") == -1);
  CHECK(!rig.store.load("nope"));

  // the wire path and the generated header agree on all 22 registers
  CHECK(uploadWire(rig.store, "dkm440"));
  std::vector<uint8_t> bin = readAll(rig.fs, "/pf/dkm440.bin");
  CHECK(bin.size() == sizeof(osos_pf_header_t) + 22 * sizeof(osos_reg_t));
  CHECK(memcmp(bin.data() + sizeof(osos_pf_header_t), kBuiltinRegs, 22 * sizeof(osos_reg_t)) == 0);
  CHECK(memcmp(bin.data(), &kBuiltin.hdr, sizeof(osos_pf_header_t)) == 0);
}

static void testRefusals() {
  std::printf("refusals\n");
  struct B { const char* what; std::string json; };
  std::vector<B> bad = {
      {"bad id", beginJson("Bad")},          {"n 0", beginJson("x1", 0)},
      {"n 49", beginJson("x1", 49)},         {"blob 1", beginJson("x1", 1, 1)},
      {"blob 9000", beginJson("x1", 1, 9000)}, {"gap", beginJson("x1", 1, 2, 2001)},
      {"tmo", beginJson("x1", 1, 2, 30, 10)}, {"blk", beginJson("x1", 1, 2, 30, 500, 65)},
      {"retries", beginJson("x1", 1, 2, 30, 500, 1, 4)},
      {"request budget", beginJson("x1", 1, 2, 30, 5000, 1, 3)}, {"rev", beginJson("x1", 1, 2, 30, 500, 1, 0, -1)},
      {"n is a string", "{\"id\":\"x1\",\"n\":\"many\",\"blob_len\":2}"},
      {"n is a float", "{\"id\":\"x1\",\"n\":1.5,\"blob_len\":2}"},
  };
  for (auto& b : bad) {
    Rig rig;
    CHECK_MSG(!run(rig.store, "profile_begin", b.json.c_str()).ok, "begin refused: %s", b.what);
  }

  {  // order and ownership
    Rig rig;
    CHECK(!run(rig.store, "profile_regs", regsJson("x1", 0, GOOD_REG).c_str()).ok);  // no begin
    CHECK(run(rig.store, "profile_begin", beginJson("x1", 2).c_str()).ok);
    CHECK(!run(rig.store, "profile_regs", regsJson("x1", 1, GOOD_REG).c_str()).ok);  // wrong index
    CHECK(run(rig.store, "profile_regs", regsJson("x1", 0, GOOD_REG).c_str()).ok);
    CHECK(!run(rig.store, "profile_regs", regsJson("zz", 1, GOOD_REG).c_str()).ok);  // other id
    CHECK(!run(rig.store, "profile_meta", "{\"id\":\"x1\",\"off\":5,\"data\":\"{}\"}").ok);
    CHECK(!run(rig.store, "profile_regs", "{\"id\":\"x1\",\"i\":1}").ok);             // no regs
  }
  {  // wire register validation, same set as the Python suite
    struct T { const char* k; const char* v; };
    for (T t : {T{"k", "\"bad key\""}, T{"t", "\"f16\""}, T{"a", "-1"}, T{"f", "1"}, T{"w", "\"mid\""},
                T{"s", "0"}, T{"d", "9"}}) {
      Rig rig;
      run(rig.store, "profile_begin", beginJson().c_str());
      ProfileResult r = run(rig.store, "profile_regs", regsJson("x1", 0, wireReg(t.k, t.v)).c_str());
      CHECK_MSG(!r.ok, "register with %s=%s refused", t.k, t.v);
    }
    Rig rig;
    run(rig.store, "profile_begin", beginJson().c_str());
    std::string wide = wireReg("a", "65535");
    JsonDocument d;
    deserializeJson(d, wide);
    d["t"] = "f32";
    std::string w2;
    serializeJson(d, w2);
    CHECK(!run(rig.store, "profile_regs", regsJson("x1", 0, w2).c_str()).ok);       // runs off the end
  }
  {  // commit must see a complete, duplicate-free upload, and leave nothing behind otherwise
    Rig rig;
    run(rig.store, "profile_begin", beginJson("x1", 2).c_str());
    run(rig.store, "profile_regs", regsJson("x1", 0, GOOD_REG).c_str());
    CHECK(!run(rig.store, "profile_commit", "{\"id\":\"x1\"}").ok);                 // 1 of 2
    run(rig.store, "profile_regs", regsJson("x1", 1, GOOD_REG).c_str());            // same key
    run(rig.store, "profile_meta", "{\"id\":\"x1\",\"off\":0,\"data\":\"{}\"}");
    ProfileResult r = run(rig.store, "profile_commit", "{\"id\":\"x1\"}");
    CHECK(!r.ok && strstr(r.detail, "duplicate"));
    CHECK(rig.fs.size("/pf/x1.bin") == -1);
  }
  {  // metadata must look like a JSON object
    Rig rig;
    run(rig.store, "profile_begin", beginJson("x1", 1, 2).c_str());
    run(rig.store, "profile_regs", regsJson("x1", 0, GOOD_REG).c_str());
    run(rig.store, "profile_meta", "{\"id\":\"x1\",\"off\":0,\"data\":\"ab\"}");
    CHECK(!run(rig.store, "profile_commit", "{\"id\":\"x1\"}").ok);
  }
  {  // flash full / flash write failure
    Rig rig;
    rig.fs.free_bytes = 1000;
    CHECK(!run(rig.store, "profile_begin", beginJson().c_str()).ok);
    rig.fs.free_bytes = 1 << 20;
    rig.fs.fail_writes = true;
    CHECK(!run(rig.store, "profile_begin", beginJson().c_str()).ok);
  }
  {  // a failed upload never damages the stored profile it was replacing
    Rig rig;
    CHECK(uploadWire(rig.store, "sdm630"));
    CHECK(run(rig.store, "profile_begin", beginJson("sdm630", 2).c_str()).ok);
    run(rig.store, "profile_regs", regsJson("sdm630", 0, GOOD_REG).c_str());
    CHECK(rig.store.load("sdm630") && rig.store.count() == 16);                    // still the old one
    CHECK(run(rig.store, "profile_begin", beginJson("other").c_str()).ok);         // a new begin cancels it
    CHECK(rig.store.load("sdm630") && rig.store.count() == 16);
  }
  {
    Rig rig;
    CHECK(!run(rig.store, "ping", "{}").handled);
  }
}

static void testStoreRules() {
  std::printf("store, assign, delete\n");
  Rig rig;
  for (int n = 0; n < OSOS_MAX_PROFILES; n++) {
    char id[16];
    snprintf(id, sizeof id, "p%d", n);
    CHECK(run(rig.store, "profile_begin", beginJson(id).c_str()).ok);
    CHECK(run(rig.store, "profile_regs", regsJson(id, 0, GOOD_REG).c_str()).ok);
    char meta[96];
    snprintf(meta, sizeof meta, "{\"id\":\"%s\",\"off\":0,\"data\":\"{}\"}", id);
    ProfileResult m = run(rig.store, "profile_meta", meta);
    CHECK_MSG(m.ok, "meta %s: %s", id, m.detail);
    char commit[48];
    snprintf(commit, sizeof commit, "{\"id\":\"%s\"}", id);
    ProfileResult c = run(rig.store, "profile_commit", commit);
    CHECK_MSG(c.ok && c.publish_list && strcmp(c.changed_profile, id) == 0, "commit %s: %s", id, c.detail);
  }
  ProfileResult full = run(rig.store, "profile_begin", beginJson("one-too-many").c_str());
  CHECK(!full.ok && strstr(full.detail, "full"));
  CHECK(run(rig.store, "profile_begin", beginJson("p0").c_str()).ok);              // replacing is still fine

  CHECK(!run(rig.store, "profile_assign", "{\"analyzer\":\"an-09\",\"profile\":\"p1\"}").ok);
  CHECK(!run(rig.store, "profile_assign", "{\"analyzer\":\"an-01\",\"profile\":\"ghost\"}").ok);
  ProfileResult as = run(rig.store, "profile_assign", "{\"analyzer\":\"an-01\",\"profile\":\"p1\"}");
  CHECK(as.ok && strcmp(as.changed_analyzer, "an-01") == 0);
  CHECK(strcmp(rig.store.effectiveId("an-01"), "p1") == 0);
  CHECK(strcmp(rig.store.effectiveId("an-02"), "dkm440") == 0);                    // default is untouched

  ProfileResult inuse = run(rig.store, "profile_delete", "{\"id\":\"p1\"}");
  CHECK(!inuse.ok && strstr(inuse.detail, "an-01"));
  CHECK(run(rig.store, "profile_delete", "{\"id\":\"p2\"}").ok);
  CHECK(!run(rig.store, "profile_delete", "{\"id\":\"nope\"}").ok);

  // assignment survives a reboot
  ProfileStore again(rig.fs, kBuiltin);
  again.begin(kAnalyzers, 2);
  CHECK(strcmp(again.effectiveId("an-01"), "p1") == 0);

  char buf[1024];
  const size_t n = rig.store.listingJson(buf, sizeof buf);
  CHECK(n > 0 && n < sizeof buf - 1);
  JsonDocument l;
  CHECK(!deserializeJson(l, buf));
  CHECK(l["v"] == 2 && l["cap"]["regs"] == 48 && l["cap"]["profiles"] == OSOS_MAX_PROFILES);
  CHECK(strcmp(l["assign"]["an-01"] | "", "p1") == 0 && strcmp(l["assign"]["an-02"] | "", "dkm440") == 0);
  bool sawBuiltin = false, sawP1 = false, sawP2 = false;
  for (JsonObjectConst p : l["profiles"].as<JsonArrayConst>()) {
    if (strcmp(p["id"] | "", "dkm440") == 0 && p["builtin"] == true) sawBuiltin = true;
    if (strcmp(p["id"] | "", "p1") == 0) sawP1 = true;
    if (strcmp(p["id"] | "", "p2") == 0) sawP2 = true;
  }
  CHECK(sawBuiltin && sawP1 && !sawP2);
}

static void testShadowing() {
  std::printf("a stored profile may shadow the built-in\n");
  Rig rig;
  CHECK(uploadWire(rig.store, "dkm440"));
  char buf[1024];
  rig.store.listingJson(buf, sizeof buf);
  JsonDocument l;
  deserializeJson(l, buf);
  int dkm = 0;
  for (JsonObjectConst p : l["profiles"].as<JsonArrayConst>())
    if (strcmp(p["id"] | "", "dkm440") == 0) { dkm++; CHECK(p["builtin"].isNull()); }
  CHECK(dkm == 1);
  ProfileResult d = run(rig.store, "profile_delete", "{\"id\":\"dkm440\"}");
  CHECK(d.ok && strcmp(d.changed_profile, "dkm440") == 0);
  CHECK(rig.store.load("dkm440") && rig.store.count() == 22);                      // built-in is back
}

static void testPowerCut() {
  std::printf("metadata that disagrees with its registers is ignored\n");
  Rig rig;
  CHECK(uploadWire(rig.store, "sdm630"));
  CHECK(rig.store.blobSize("sdm630") > 0);
  rig.fs.write("/pf/sdm630.js", "{}", 2, false);       // as if only the .js rename had landed
  CHECK(rig.store.blobSize("sdm630") == -1);
  CHECK(rig.store.load("sdm630") && rig.store.count() == 16);                      // registers still usable
}

static void testTestCommand() {
  std::printf("profile_test\n");
  Rig rig;
  ProfileResult r = run(rig.store, "profile_test",
                        "{\"analyzer\":\"an-01\",\"address\":260,\"fc\":3,\"type\":\"f32\"}");
  CHECK(r.ok && r.want_test && r.test_reg.address == 260 && r.test_reg.type == OSOS_T_F32 &&
        r.test_raw_words == 0 && strcmp(r.test_analyzer, "an-01") == 0);
  uint16_t w[2] = {0x41D4, 0x0000};
  char out[96];
  ProfileStore::describeTest(r, w, 2, out, sizeof out);
  CHECK_MSG(strcmp(out, "raw=41D4 0000 value=26.500") == 0, "got '%s'", out);

  uint16_t nanw[2] = {0x7FC0, 0};
  ProfileStore::describeTest(r, nanw, 2, out, sizeof out);
  CHECK_MSG(strstr(out, "n/a"), "got '%s'", out);

  r = run(rig.store, "profile_test", "{\"analyzer\":\"an-01\",\"address\":10,\"fc\":4,\"count\":3}");
  CHECK(r.ok && r.want_test && r.test_raw_words == 3 && r.test_reg.fc == 4);
  uint16_t w3[3] = {1, 0xABCD, 0xFFFF};
  ProfileStore::describeTest(r, w3, 3, out, sizeof out);
  CHECK_MSG(strcmp(out, "raw=0001 ABCD FFFF") == 0, "got '%s'", out);

  r = run(rig.store, "profile_test",
          "{\"analyzer\":\"an-01\",\"address\":0,\"type\":\"u16\",\"scale\":0.1,\"decimals\":1}");
  uint16_t u[1] = {2305};
  ProfileStore::describeTest(r, u, 1, out, sizeof out);
  CHECK_MSG(strcmp(out, "raw=0901 value=230.5") == 0, "got '%s'", out);

  CHECK(!run(rig.store, "profile_test", "{\"analyzer\":\"zz\",\"address\":0}").ok);
  CHECK(!run(rig.store, "profile_test", "{\"analyzer\":\"an-01\",\"address\":70000}").ok);
  CHECK(!run(rig.store, "profile_test", "{\"analyzer\":\"an-01\",\"address\":0,\"fc\":9}").ok);
  CHECK(!run(rig.store, "profile_test", "{\"analyzer\":\"an-01\",\"address\":0,\"count\":9}").ok);
  CHECK(!run(rig.store, "profile_test", "{\"analyzer\":\"an-01\",\"address\":0,\"type\":\"x\"}").ok);
}

static void testFormat() {
  std::printf("number formatting\n");
  char b[32];
  osos_format(26.5, 3, b, sizeof b);   CHECK(strcmp(b, "26.500") == 0);
  osos_format(-10, 0, b, sizeof b);    CHECK(strcmp(b, "-10") == 0);
  osos_format(230.5, 1, b, sizeof b);  CHECK(strcmp(b, "230.5") == 0);
  // the scale is a double: a float 0.001 would print 1000000.05 here
  osos_reg_t r = mkReg("u32", "big", "big", 0.001, 0);
  uint16_t w[2] = {0x3B9A, 0xCA00};    // 1e9
  double v = 0;
  CHECK(osos_decode(&r, w, &v));
  osos_format(v, 2, b, sizeof b);
  CHECK_MSG(strcmp(b, "1000000.00") == 0, "got %s", b);
}

int main() {
  loadVectors();
  testDecode();
  testPlan();
  testPoll();
  testWireAndRecords();
  testBuiltin();
  testRefusals();
  testStoreRules();
  testShadowing();
  testPowerCut();
  testTestCommand();
  testFormat();
  std::printf("\n%d checks, %d failed\n", g_checks, g_failed);
  return g_failed ? 1 : 0;
}
