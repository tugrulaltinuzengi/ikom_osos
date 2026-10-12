// Meter profile store for the ESP32 gateway. See profile.h.
#include "profile.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "osos_builtin_dkm440.h"

#define KEY_BIN "pf_bin"
#define KEY_JS  "pf_js"

static osos_pf_header_t s_hdr;
static osos_reg_t s_regs[OSOS_MAX_REGS];
static bool s_builtin = true;
static char s_id[25];
static uint32_t s_generation;

// Upload in progress. Staged in RAM and committed in one go, so a failed or
// abandoned upload never touches the working profile.
static struct {
    bool active;
    char id[25];
    osos_pf_header_t hdr;
    osos_reg_t *regs;
    char *blob;
    uint8_t got;
    uint16_t blob_got;
} up;

// ------------------------------------------------------------------ helpers --
static bool valid_id(const char *s)
{
    if (!s) return false;
    size_t n = strlen(s);
    if (n < 1 || n > 24) return false;
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || (i > 0 && (c == '_' || c == '-'));
        if (!ok) return false;
    }
    return true;
}

static bool valid_key(const char *s)
{
    if (!s) return false;
    size_t n = strlen(s);
    if (n < 1 || n > 31) return false;
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')) return false;
    }
    return true;
}

static bool valid_header(const osos_pf_header_t *h)
{
    return memcmp(h->magic, OSOS_PF_MAGIC, 4) == 0 && h->ver == OSOS_PF_VER && h->n >= 1 && h->n <= OSOS_MAX_REGS;
}

static const cJSON *member(const cJSON *o, const char *k)
{
    return o ? cJSON_GetObjectItemCaseSensitive((cJSON *)o, k) : NULL;
}

// An integer argument; `dflt` when absent; INT_MIN-ish when present but not an integer.
#define NOT_AN_INT (-2147483647)
static int int_arg(const cJSON *o, const char *k, int dflt)
{
    const cJSON *v = member(o, k);
    if (!v || cJSON_IsNull(v)) return dflt;
    if (!cJSON_IsNumber(v)) return NOT_AN_INT;
    double d = v->valuedouble;
    if (d != floor(d) || d > 2147483000.0 || d < -2147483000.0) return NOT_AN_INT;
    return (int)d;
}

static bool range_arg(const cJSON *o, const char *k, int dflt, int lo, int hi, int *out)
{
    int x = int_arg(o, k, dflt);
    if (x < lo || x > hi) return false;
    *out = x;
    return true;
}

static const char *str_arg(const cJSON *o, const char *k)
{
    const cJSON *v = member(o, k);
    return cJSON_IsString(v) && v->valuestring ? v->valuestring : "";
}

// One register in wire form {k,a,f,t,w,b,s,o,d} -> binary record. Returns why it
// was refused, or NULL.
static const char *parse_wire_reg(const cJSON *e, osos_reg_t *out)
{
    memset(out, 0, sizeof *out);
    const char *k = str_arg(e, "k");
    if (!valid_key(k)) return "bad key";
    int t = osos_type_from_name(str_arg(e, "t"));
    if (t < 0) return "bad type";
    int a = int_arg(e, "a", -1);
    if (a < 0 || a + osos_type_words((uint8_t)t) > 65536) return "address out of range";
    int f = int_arg(e, "f", -1);
    if (f != 3 && f != 4) return "fc must be 3 or 4";
    const char *w = str_arg(e, "w"), *b = str_arg(e, "b");
    if ((strcmp(w, "big") && strcmp(w, "little")) || (strcmp(b, "big") && strcmp(b, "little")))
        return "bad word/byte order";
    const cJSON *s = member(e, "s"), *o = member(e, "o");
    if (!cJSON_IsNumber(s) || !cJSON_IsNumber(o) || s->valuedouble == 0) return "bad scale/offset";
    int d = int_arg(e, "d", -1);
    if (d < 0 || d > 6) return "decimals out of range";
    strncpy(out->key, k, sizeof out->key - 1);
    out->scale = s->valuedouble;
    out->offset = o->valuedouble;
    out->address = (uint16_t)a;
    out->fc = (uint8_t)f;
    out->type = (uint8_t)t;
    out->order = (uint8_t)((strcmp(w, "little") == 0 ? OSOS_ORDER_WORD_LITTLE : 0) |
                           (strcmp(b, "little") == 0 ? OSOS_ORDER_BYTE_LITTLE : 0));
    out->decimals = (uint8_t)d;
    return NULL;
}

static void free_upload(void)
{
    free(up.regs);
    free(up.blob);
    memset(&up, 0, sizeof up);
}

static void use_builtin(void)
{
    s_hdr = kBuiltin.hdr;
    memcpy(s_regs, kBuiltin.regs, (size_t)s_hdr.n * sizeof(osos_reg_t));
    s_builtin = true;
    snprintf(s_id, sizeof s_id, "%s", kBuiltin.id);
}

// ------------------------------------------------------------------ lifecycle --
static void init_locked(void);

void profile_init(void)
{
    profile_lock();
    init_locked();
    profile_unlock();
}

uint32_t profile_generation(void) { return s_generation; }

static void init_locked(void)
{
    s_generation++;
    free_upload();
    uint8_t *buf = malloc(sizeof(osos_pf_header_t) + OSOS_MAX_REGS * sizeof(osos_reg_t));
    if (buf) {
        size_t len = sizeof(osos_pf_header_t) + OSOS_MAX_REGS * sizeof(osos_reg_t);
        osos_pf_header_t h;
        if (profile_store_read(KEY_BIN, buf, &len) && len >= sizeof h) {
            memcpy(&h, buf, sizeof h);
            if (valid_header(&h) && len == sizeof h + (size_t)h.n * sizeof(osos_reg_t)) {
                // the id is the one inside the metadata; keep it for `profile_id()`
                s_hdr = h;
                memcpy(s_regs, buf + sizeof h, (size_t)h.n * sizeof(osos_reg_t));
                s_builtin = false;
                s_id[0] = 0;
                char *js = malloc(PROFILE_MAX_BLOB + 1);
                size_t jl = PROFILE_MAX_BLOB;
                if (js && profile_store_read(KEY_JS, js, &jl) && jl == h.blob_len) {
                    js[jl] = 0;
                    cJSON *doc = cJSON_Parse(js);
                    const cJSON *id = member(doc, "id");
                    if (cJSON_IsString(id)) snprintf(s_id, sizeof s_id, "%s", id->valuestring);
                    cJSON_Delete(doc);
                }
                free(js);
                if (!s_id[0]) snprintf(s_id, sizeof s_id, "stored");
                free(buf);
                return;
            }
        }
        free(buf);
    }
    use_builtin();
}

const osos_pf_header_t *profile_header(void) { return &s_hdr; }
const osos_reg_t *profile_regs(void) { return s_regs; }
int profile_count(void) { return s_hdr.n; }
const char *profile_id(void) { return s_id; }
bool profile_is_builtin(void) { return s_builtin; }

osos_timing_t profile_timing(void)
{
    osos_timing_t t;
    t.gap_ms = s_hdr.gap_ms;
    t.timeout_ms = s_hdr.timeout_ms;
    t.max_block = s_hdr.max_block;
    t.retries = s_hdr.retries;
    return t;
}

int profile_blob_size(void)
{
    if (s_builtin) return kBuiltin.hdr.blob_len;
    size_t len = 0;
    char *js = malloc(PROFILE_MAX_BLOB);
    if (!js) return -1;
    len = PROFILE_MAX_BLOB;
    bool ok = profile_store_read(KEY_JS, js, &len);
    free(js);
    // A power cut between the two writes of a commit leaves metadata that does not
    // belong to the registers; it is ignored rather than shown against them.
    return (ok && len == s_hdr.blob_len) ? (int)len : -1;
}

int profile_blob_read(size_t off, uint8_t *buf, size_t n)
{
    int total = profile_blob_size();
    if (total < 0 || off >= (size_t)total) return -1;
    if (off + n > (size_t)total) n = (size_t)total - off;
    if (s_builtin) {
        memcpy(buf, kBuiltin.blob + off, n);
        return (int)n;
    }
    char *js = malloc(PROFILE_MAX_BLOB);
    if (!js) return -1;
    size_t len = PROFILE_MAX_BLOB;
    if (!profile_store_read(KEY_JS, js, &len)) { free(js); return -1; }
    memcpy(buf, js + off, n);
    free(js);
    return (int)n;
}

// ------------------------------------------------------------------- commands --
#define FAIL(...) do { snprintf(r.detail, sizeof r.detail, __VA_ARGS__); return r; } while (0)

static bool mine(const cJSON *a)
{
    return up.active && strcmp(str_arg(a, "id"), up.id) == 0;
}

static profile_result_t cmd_begin(const cJSON *a, profile_result_t r)
{
    free_upload();
    const char *id = str_arg(a, "id");
    if (!valid_id(id)) FAIL("bad profile id");
    int n = int_arg(a, "n", -1), bl = int_arg(a, "blob_len", -1);
    if (n < 1 || n > OSOS_MAX_REGS) FAIL("n out of range 1..%d", OSOS_MAX_REGS);
    if (bl < 2 || bl > PROFILE_MAX_BLOB) FAIL("blob_len out of range 2..%d", PROFILE_MAX_BLOB);
    osos_pf_header_t h;
    memset(&h, 0, sizeof h);
    memcpy(h.magic, OSOS_PF_MAGIC, 4);
    h.ver = OSOS_PF_VER;
    h.n = (uint8_t)n;
    h.blob_len = (uint16_t)bl;
    int v;
    if (!range_arg(a, "rev", 1, 0, 65535, &v)) FAIL("rev out of range 0..65535");
    h.rev = (uint16_t)v;
    if (!range_arg(a, "gap", 30, 0, 2000, &v)) FAIL("gap out of range 0..2000");
    h.gap_ms = (uint16_t)v;
    if (!range_arg(a, "tmo", 500, 50, 5000, &v)) FAIL("tmo out of range 50..5000");
    h.timeout_ms = (uint16_t)v;
    if (!range_arg(a, "blk", 1, 1, 64, &v)) FAIL("blk out of range 1..64");
    h.max_block = (uint8_t)v;
    if (!range_arg(a, "retries", 0, 0, 3, &v)) FAIL("retries out of range 0..3");
    h.retries = (uint8_t)v;
    if ((int)h.timeout_ms * ((int)h.retries + 1) > 8000) FAIL("timeout x attempts exceeds 8000 ms");
    const char *name = str_arg(a, "name");
    if (strlen(name) > 44) FAIL("name too long");
    strncpy(h.name, name, sizeof h.name - 1);

    up.regs = malloc((size_t)n * sizeof(osos_reg_t));
    up.blob = malloc((size_t)bl);
    if (!up.regs || !up.blob) { free_upload(); FAIL("out of memory"); }
    up.active = true;
    up.hdr = h;
    snprintf(up.id, sizeof up.id, "%s", id);
    r.ok = true;
    snprintf(r.detail, sizeof r.detail, "upload %s started", id);
    return r;
}

static profile_result_t cmd_regs(const cJSON *a, profile_result_t r)
{
    if (!mine(a)) FAIL("no upload in progress for that id");
    if (int_arg(a, "i", -1) != up.got) FAIL("out of order, expected index %u", up.got);
    const cJSON *arr = member(a, "regs");
    int cnt = cJSON_IsArray(arr) ? cJSON_GetArraySize(arr) : 0;
    if (cnt < 1 || cnt > 8) FAIL("regs must hold 1..8 entries");
    if (up.got + cnt > up.hdr.n) FAIL("more registers than declared");
    osos_reg_t tmp[8];
    int i = 0;
    const cJSON *e;
    cJSON_ArrayForEach(e, arr) {
        const char *why = parse_wire_reg(e, &tmp[i]);
        if (why) FAIL("reg %d: %s", up.got + i, why);
        i++;
    }
    memcpy(up.regs + up.got, tmp, (size_t)cnt * sizeof(osos_reg_t));
    up.got = (uint8_t)(up.got + cnt);
    r.ok = true;
    snprintf(r.detail, sizeof r.detail, "%u/%u regs", up.got, up.hdr.n);
    return r;
}

static profile_result_t cmd_meta(const cJSON *a, profile_result_t r)
{
    if (!mine(a)) FAIL("no upload in progress for that id");
    if (int_arg(a, "off", -1) != up.blob_got) FAIL("out of order, expected offset %u", up.blob_got);
    const char *data = str_arg(a, "data");
    size_t len = strlen(data);
    if (len == 0) FAIL("data must be a non-empty string");
    if (up.blob_got + len > up.hdr.blob_len) FAIL("more metadata than declared");
    memcpy(up.blob + up.blob_got, data, len);
    up.blob_got = (uint16_t)(up.blob_got + len);
    r.ok = true;
    snprintf(r.detail, sizeof r.detail, "%u/%u bytes", up.blob_got, up.hdr.blob_len);
    return r;
}

static profile_result_t cmd_commit(const cJSON *a, profile_result_t r)
{
    if (!mine(a)) FAIL("no upload in progress for that id");
    if (up.got != up.hdr.n) FAIL("incomplete: %u/%u regs", up.got, up.hdr.n);
    if (up.blob_got != up.hdr.blob_len) FAIL("incomplete: %u/%u bytes", up.blob_got, up.hdr.blob_len);
    for (int i = 0; i < up.hdr.n; i++)
        for (int j = i + 1; j < up.hdr.n; j++)
            if (strcmp(up.regs[i].key, up.regs[j].key) == 0) FAIL("duplicate register key");
    if (up.blob[0] != '{' || up.blob[up.hdr.blob_len - 1] != '}') FAIL("metadata is not a JSON object");

    size_t binlen = sizeof up.hdr + (size_t)up.hdr.n * sizeof(osos_reg_t);
    uint8_t *bin = malloc(binlen);
    if (!bin) FAIL("out of memory");
    memcpy(bin, &up.hdr, sizeof up.hdr);
    memcpy(bin + sizeof up.hdr, up.regs, (size_t)up.hdr.n * sizeof(osos_reg_t));
    // Metadata first: if power fails between the writes the lengths disagree and
    // profile_blob_size() ignores it instead of labelling the old registers wrongly.
    bool ok = profile_store_write(KEY_JS, up.blob, up.hdr.blob_len) && profile_store_write(KEY_BIN, bin, binlen);
    free(bin);
    if (!ok) FAIL("flash write failed");

    char id[25];
    uint16_t rev = up.hdr.rev;
    uint8_t n = up.hdr.n;
    snprintf(id, sizeof id, "%s", up.id);
    free_upload();
    init_locked();                       // activate what was just stored
    r.ok = true;
    r.changed = true;
    snprintf(r.detail, sizeof r.detail, "stored %s rev %u (%u regs)", id, rev, n);
    return r;
}

static profile_result_t cmd_delete(const cJSON *a, profile_result_t r)
{
    const char *id = str_arg(a, "id");
    if (s_builtin || strcmp(id, s_id) != 0) FAIL("no such stored profile");
    profile_store_erase(KEY_BIN);
    profile_store_erase(KEY_JS);
    init_locked();                       // the built-in takes over
    r.ok = true;
    r.changed = true;
    snprintf(r.detail, sizeof r.detail, "deleted %s", id);
    return r;
}

static profile_result_t cmd_test(const cJSON *a, profile_result_t r)
{
    int addr = int_arg(a, "address", -1);
    if (addr < 0 || addr > 65535) FAIL("address out of range");
    int fc = int_arg(a, "fc", 3);
    if (fc != 3 && fc != 4) FAIL("fc must be 3 or 4");
    memset(&r.test_reg, 0, sizeof r.test_reg);
    r.test_reg.address = (uint16_t)addr;
    r.test_reg.fc = (uint8_t)fc;
    r.test_reg.scale = 1;
    int count = int_arg(a, "count", 0);
    if (count != 0) {
        if (count < 1 || count > 8 || addr + count > 65536) FAIL("count must be 1..8 within the address space");
        r.test_raw_words = (uint8_t)count;
    } else {
        cJSON *wire = cJSON_CreateObject();
        cJSON_AddStringToObject(wire, "k", "T");
        cJSON_AddNumberToObject(wire, "a", addr);
        cJSON_AddNumberToObject(wire, "f", fc);
        const char *t = str_arg(a, "type");
        cJSON_AddStringToObject(wire, "t", t[0] ? t : "f32");
        const char *w = str_arg(a, "word_order"), *b = str_arg(a, "byte_order");
        cJSON_AddStringToObject(wire, "w", w[0] ? w : "big");
        cJSON_AddStringToObject(wire, "b", b[0] ? b : "big");
        const cJSON *s = member(a, "scale"), *o = member(a, "offset");
        cJSON_AddNumberToObject(wire, "s", cJSON_IsNumber(s) ? s->valuedouble : 1.0);
        cJSON_AddNumberToObject(wire, "o", cJSON_IsNumber(o) ? o->valuedouble : 0.0);
        cJSON_AddNumberToObject(wire, "d", int_arg(a, "decimals", 3));
        osos_reg_t tmp;
        const char *why = parse_wire_reg(wire, &tmp);
        cJSON_Delete(wire);
        if (why) FAIL("%s", why);
        r.test_reg = tmp;
    }
    r.ok = true;
    r.want_test = true;
    snprintf(r.detail, sizeof r.detail, "testing");
    return r;
}

static profile_result_t dispatch(const char *action, const cJSON *args)
{
    profile_result_t r;
    memset(&r, 0, sizeof r);
    r.handled = true;
    if (!strcmp(action, "profile_begin")) return cmd_begin(args, r);
    if (!strcmp(action, "profile_regs")) return cmd_regs(args, r);
    if (!strcmp(action, "profile_meta")) return cmd_meta(args, r);
    if (!strcmp(action, "profile_commit")) return cmd_commit(args, r);
    if (!strcmp(action, "profile_delete")) return cmd_delete(args, r);
    if (!strcmp(action, "profile_test")) return cmd_test(args, r);
    if (!strcmp(action, "profile_list")) {
        r.ok = true;
        r.changed = true;               // republish
        snprintf(r.detail, sizeof r.detail, "listing republished");
        return r;
    }
    r.handled = false;
    return r;
}

profile_result_t profile_handle(const char *action, const cJSON *args)
{
    profile_lock();
    profile_result_t r = dispatch(action, args);
    profile_unlock();
    return r;
}

void profile_describe_test(const profile_result_t *r, const uint16_t *w, uint8_t n, char *out, size_t outn)
{
    size_t pos = (size_t)snprintf(out, outn, "raw=");
    for (uint8_t i = 0; i < n && pos + 6 < outn; i++)
        pos += (size_t)snprintf(out + pos, outn - pos, i ? " %04X" : "%04X", w[i]);
    if (r->test_raw_words) return;
    double v;
    char num[32];
    if (osos_decode(&r->test_reg, w, &v)) {
        osos_format(v, r->test_reg.decimals, num, sizeof num);
        snprintf(out + pos, outn - pos, " value=%s", num);
    } else {
        snprintf(out + pos, outn - pos, " value=n/a (not finite)");
    }
}
