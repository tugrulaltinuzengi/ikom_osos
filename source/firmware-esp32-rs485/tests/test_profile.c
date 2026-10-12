// Host tests for main/profile.c (ESP32 profile store), against the shared vectors.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "profile.h"

static int g_checks, g_failed;
#define CHECK(c) do { g_checks++; if (!(c)) { g_failed++; printf("  FAIL %s:%d  %s\n", __FILE__, __LINE__, #c); } } while (0)
#define CHECKF(c, ...) do { g_checks++; if (!(c)) { g_failed++; printf("  FAIL %s:%d  %s  ", __FILE__, __LINE__, #c); printf(__VA_ARGS__); printf("\n"); } } while (0)

void profile_lock(void) {}
void profile_unlock(void) {}

// ---- NVS stand-in
#define SLOTS 4
static struct { char key[16]; uint8_t *data; size_t len; } store[SLOTS];
static bool fail_writes;

bool profile_store_read(const char *key, void *buf, size_t *len)
{
    for (int i = 0; i < SLOTS; i++)
        if (store[i].data && !strcmp(store[i].key, key)) {
            if (store[i].len > *len) return false;
            memcpy(buf, store[i].data, store[i].len);
            *len = store[i].len;
            return true;
        }
    return false;
}
bool profile_store_write(const char *key, const void *buf, size_t len)
{
    if (fail_writes) return false;
    int slot = -1;
    for (int i = 0; i < SLOTS; i++) if (store[i].data && !strcmp(store[i].key, key)) slot = i;
    for (int i = 0; slot < 0 && i < SLOTS; i++) if (!store[i].data) slot = i;
    if (slot < 0) return false;
    free(store[slot].data);
    store[slot].data = malloc(len);
    memcpy(store[slot].data, buf, len);
    store[slot].len = len;
    snprintf(store[slot].key, sizeof store[slot].key, "%s", key);
    return true;
}
bool profile_store_erase(const char *key)
{
    for (int i = 0; i < SLOTS; i++)
        if (store[i].data && !strcmp(store[i].key, key)) { free(store[i].data); store[i].data = NULL; return true; }
    return false;
}
static void wipe(void) { for (int i = 0; i < SLOTS; i++) { free(store[i].data); store[i].data = NULL; } fail_writes = false; }

// ---- helpers
static cJSON *VEC;
static cJSON *load_vectors(void)
{
    FILE *f = fopen("../../meter-profiles/vectors.json", "rb");
    if (!f) { printf("cannot open vectors.json\n"); exit(2); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *s = malloc(n + 1);
    if (fread(s, 1, n, f) != (size_t)n) exit(2);
    s[n] = 0; fclose(f);
    cJSON *j = cJSON_Parse(s);
    free(s);
    if (!j) { printf("vectors.json does not parse\n"); exit(2); }
    return j;
}

static profile_result_t run(const char *action, const char *json)
{
    cJSON *a = cJSON_Parse(json);
    profile_result_t r = profile_handle(action, a);
    cJSON_Delete(a);
    return r;
}

static bool upload(const char *name)
{
    cJSON *cmds = cJSON_GetObjectItem(cJSON_GetObjectItem(cJSON_GetObjectItem(VEC, "wire"), name), "commands");
    bool all = true;
    cJSON *c;
    cJSON_ArrayForEach(c, cmds) {
        profile_result_t r = profile_handle(cJSON_GetObjectItem(c, "action")->valuestring, cJSON_GetObjectItem(c, "args"));
        if (!r.ok) { printf("    %s: %s\n", cJSON_GetObjectItem(c, "action")->valuestring, r.detail); all = false; }
    }
    return all;
}

static void hex(const uint8_t *p, size_t n, char *out) { for (size_t i = 0; i < n; i++) sprintf(out + 2 * i, "%02x", p[i]); }

static const char *GOOD = "{\"k\":\"A\",\"a\":0,\"f\":3,\"t\":\"u16\",\"w\":\"big\",\"b\":\"big\",\"s\":1,\"o\":0,\"d\":0}";
static void begin(const char *id, int n, int bl, int tmo, int retries)
{
    char b[200];
    snprintf(b, sizeof b, "{\"id\":\"%s\",\"name\":\"T\",\"rev\":1,\"n\":%d,\"blob_len\":%d,\"gap\":30,\"tmo\":%d,\"blk\":1,\"retries\":%d}", id, n, bl, tmo, retries);
    profile_result_t r = run("profile_begin", b);
    CHECKF(r.ok, "%s", r.detail);
}
static char *regs_json(const char *id, int i, const char *reg)
{
    static char b[400];
    snprintf(b, sizeof b, "{\"id\":\"%s\",\"i\":%d,\"regs\":[%s]}", id, i, reg);
    return b;
}

// ---- tests
static void test_builtin(void)
{
    printf("built-in DKM-440\n");
    wipe(); profile_init();
    CHECK(profile_is_builtin() && profile_count() == 22 && !strcmp(profile_id(), "dkm440"));
    CHECK(!strcmp(profile_regs()[0].key, "Supply_Voltage") && profile_regs()[0].address == 260);
    CHECK(profile_timing().gap_ms == 30 && profile_timing().max_block == 1);
    CHECK(profile_blob_size() == 3087);
    char head[32] = {0};
    CHECK(profile_blob_read(0, (uint8_t *)head, 25) == 25 && !strncmp(head, "{\"schema\":1,\"id\":\"dkm440\"", 25));
    cJSON *rec;
    cJSON_ArrayForEach(rec, cJSON_GetObjectItem(VEC, "records")) {
        if (strcmp(cJSON_GetObjectItem(rec, "file")->valuestring, "dkm440.json")) continue;
        char h[200];
        hex((const uint8_t *)&profile_regs()[cJSON_GetObjectItem(rec, "index")->valueint], sizeof(osos_reg_t), h);
        CHECK(!strcmp(h, cJSON_GetObjectItem(rec, "hex")->valuestring));
    }
}

static void test_upload_and_persist(void)
{
    printf("upload, activate, reboot, delete\n");
    wipe(); profile_init();
    CHECK(upload("sdm630"));
    CHECK(!profile_is_builtin() && !strcmp(profile_id(), "sdm630") && profile_count() == 16);
    CHECK(profile_timing().max_block == 16 && profile_timing().retries == 1);
    // the vectors pin the stored bytes
    cJSON *rec;
    cJSON_ArrayForEach(rec, cJSON_GetObjectItem(VEC, "records")) {
        if (!strstr(cJSON_GetObjectItem(rec, "file")->valuestring, "sdm630")) continue;
        char h[200];
        hex((const uint8_t *)&profile_regs()[cJSON_GetObjectItem(rec, "index")->valueint], sizeof(osos_reg_t), h);
        CHECK(!strcmp(h, cJSON_GetObjectItem(rec, "hex")->valuestring));
    }
    int bl = profile_blob_size();
    CHECK(bl > 100);
    char *blob = calloc(bl + 1, 1);
    CHECK(profile_blob_read(0, (uint8_t *)blob, bl) == bl);
    cJSON *doc = cJSON_Parse(blob);
    CHECK(doc && !strcmp(cJSON_GetObjectItem(doc, "id")->valuestring, "sdm630"));
    cJSON_Delete(doc); free(blob);

    profile_init();                                  // "reboot": comes back from storage
    CHECK(!profile_is_builtin() && !strcmp(profile_id(), "sdm630") && profile_count() == 16);

    profile_result_t r = run("profile_delete", "{\"id\":\"sdm630\"}");
    CHECK(r.ok && r.changed && profile_is_builtin() && profile_count() == 22);
    CHECK(!run("profile_delete", "{\"id\":\"sdm630\"}").ok);          // nothing stored any more
    CHECK(!run("profile_delete", "{\"id\":\"dkm440\"}").ok);          // the built-in cannot be deleted
}

static void test_refusals(void)
{
    printf("refusals\n");
    wipe(); profile_init();
    char b[200];
    struct { const char *what; int n, bl, tmo, retries; const char *id; } bad[] = {
        {"bad id", 1, 2, 500, 0, "Bad"}, {"n 0", 0, 2, 500, 0, "x1"}, {"n 49", 49, 2, 500, 0, "x1"},
        {"blob 1", 1, 1, 500, 0, "x1"}, {"blob 9000", 1, 9000, 500, 0, "x1"}, {"tmo", 1, 2, 10, 0, "x1"},
        {"retries", 1, 2, 500, 4, "x1"}, {"budget", 1, 2, 5000, 3, "x1"},
    };
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        snprintf(b, sizeof b, "{\"id\":\"%s\",\"n\":%d,\"blob_len\":%d,\"tmo\":%d,\"retries\":%d}", bad[i].id, bad[i].n, bad[i].bl, bad[i].tmo, bad[i].retries);
        CHECKF(!run("profile_begin", b).ok, "begin refused: %s", bad[i].what);
    }
    CHECK(!run("profile_begin", "{\"id\":\"x1\",\"n\":\"many\",\"blob_len\":2}").ok);
    CHECK(!run("profile_begin", "{\"id\":\"x1\",\"n\":1.5,\"blob_len\":2}").ok);

    CHECK(!run("profile_regs", regs_json("x1", 0, GOOD)).ok);                 // no upload
    begin("x1", 2, 2, 500, 0);
    CHECK(!run("profile_regs", regs_json("x1", 1, GOOD)).ok);                 // wrong index
    CHECK(run("profile_regs", regs_json("x1", 0, GOOD)).ok);
    CHECK(!run("profile_regs", regs_json("zz", 1, GOOD)).ok);                 // other id
    CHECK(!run("profile_meta", "{\"id\":\"x1\",\"off\":5,\"data\":\"{}\"}").ok);
    CHECK(!run("profile_commit", "{\"id\":\"x1\"}").ok);                      // 1 of 2 registers
    CHECK(run("profile_regs", regs_json("x1", 1, GOOD)).ok);                  // same key again
    CHECK(run("profile_meta", "{\"id\":\"x1\",\"off\":0,\"data\":\"{}\"}").ok);
    profile_result_t r = run("profile_commit", "{\"id\":\"x1\"}");
    CHECK(!r.ok && strstr(r.detail, "duplicate"));
    CHECK(profile_is_builtin());                                              // nothing half-stored

    struct { const char *k, *v; } regs[] = { {"k", "\"bad key\""}, {"t", "\"f16\""}, {"a", "-1"}, {"f", "1"}, {"w", "\"mid\""}, {"s", "0"}, {"d", "9"} };
    for (size_t i = 0; i < sizeof regs / sizeof regs[0]; i++) {
        begin("x1", 1, 2, 500, 0);
        cJSON *reg = cJSON_Parse(GOOD);
        cJSON_ReplaceItemInObject(reg, regs[i].k, cJSON_Parse(regs[i].v));
        char *rs = cJSON_PrintUnformatted(reg);
        CHECKF(!run("profile_regs", regs_json("x1", 0, rs)).ok, "register with %s=%s refused", regs[i].k, regs[i].v);
        free(rs); cJSON_Delete(reg);
    }
    begin("x1", 1, 2, 500, 0);
    CHECK(!run("profile_regs", regs_json("x1", 0, "{\"k\":\"A\",\"a\":65535,\"f\":3,\"t\":\"f32\",\"w\":\"big\",\"b\":\"big\",\"s\":1,\"o\":0,\"d\":0}")).ok);

    begin("x1", 1, 2, 500, 0);                                                 // metadata must look like JSON
    CHECK(run("profile_regs", regs_json("x1", 0, GOOD)).ok);
    CHECK(run("profile_meta", "{\"id\":\"x1\",\"off\":0,\"data\":\"ab\"}").ok);
    CHECK(!run("profile_commit", "{\"id\":\"x1\"}").ok);

    begin("x1", 1, 2, 500, 0);                                                 // a write failure leaves the old profile
    run("profile_regs", regs_json("x1", 0, GOOD));
    run("profile_meta", "{\"id\":\"x1\",\"off\":0,\"data\":\"{}\"}");
    fail_writes = true;
    CHECK(!run("profile_commit", "{\"id\":\"x1\"}").ok);
    fail_writes = false;
    CHECK(profile_is_builtin() && profile_count() == 22);
    CHECK(!profile_handle("ping", NULL).handled);
}

static void test_power_cut(void)
{
    printf("metadata that disagrees with its registers is ignored\n");
    wipe(); profile_init();
    CHECK(upload("generic-int"));
    CHECK(profile_blob_size() > 0);
    profile_store_write("pf_js", "{}", 2);                // as if only the metadata write had landed
    CHECK(profile_blob_size() == -1);
    profile_init();
    CHECK(profile_count() == 5);                          // registers are still usable
}

static void test_test_command(void)
{
    printf("profile_test\n");
    wipe(); profile_init();
    profile_result_t r = run("profile_test", "{\"analyzer\":\"an-01\",\"address\":260,\"fc\":3,\"type\":\"f32\"}");
    CHECK(r.ok && r.want_test && r.test_reg.address == 260 && r.test_reg.type == OSOS_T_F32 && r.test_raw_words == 0);
    uint16_t w[2] = {0x41D4, 0};
    char out[96];
    profile_describe_test(&r, w, 2, out, sizeof out);
    CHECKF(!strcmp(out, "raw=41D4 0000 value=26.500"), "got '%s'", out);
    uint16_t nanw[2] = {0x7FC0, 0};
    profile_describe_test(&r, nanw, 2, out, sizeof out);
    CHECK(strstr(out, "n/a"));
    r = run("profile_test", "{\"address\":10,\"fc\":4,\"count\":3}");
    CHECK(r.ok && r.test_raw_words == 3 && r.test_reg.fc == 4);
    uint16_t w3[3] = {1, 0xABCD, 0xFFFF};
    profile_describe_test(&r, w3, 3, out, sizeof out);
    CHECKF(!strcmp(out, "raw=0001 ABCD FFFF"), "got '%s'", out);
    r = run("profile_test", "{\"address\":0,\"type\":\"u16\",\"scale\":0.1,\"decimals\":1}");
    uint16_t u[1] = {2305};
    profile_describe_test(&r, u, 1, out, sizeof out);
    CHECKF(!strcmp(out, "raw=0901 value=230.5"), "got '%s'", out);
    CHECK(!run("profile_test", "{\"address\":70000}").ok);
    CHECK(!run("profile_test", "{\"address\":0,\"fc\":9}").ok);
    CHECK(!run("profile_test", "{\"address\":0,\"count\":9}").ok);
    CHECK(!run("profile_test", "{\"address\":0,\"type\":\"x\"}").ok);
    CHECK(run("profile_list", "{}").changed);
}

int main(void)
{
    VEC = load_vectors();
    test_builtin();
    test_upload_and_persist();
    test_refusals();
    test_power_cut();
    test_test_command();
    printf("\n%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
