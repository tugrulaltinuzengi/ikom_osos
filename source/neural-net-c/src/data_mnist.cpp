#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "data_mnist.hpp"

/* Every failure path funnels here: clear message + how to get the data
 * (SRS NN-9).  Returns false so the caller can just `return fail(...)`. */
static bool fail(const char *path, const char *what) {
    std::fprintf(stderr,
        "error: %s '%s'\n"
        "The MNIST data files belong in ./data (about 11 MB packed). Download:\n"
        "  curl -L -o data/train-images-idx3-ubyte.gz "
        "https://ossci-datasets.s3.amazonaws.com/mnist/train-images-idx3-ubyte.gz\n"
        "  (repeat for train-labels-idx1-ubyte, t10k-images-idx3-ubyte,\n"
        "   t10k-labels-idx1-ubyte), then:  gzip -d data/*.gz\n"
        "Mirrors and the CSV fallback format: EXPLANATION.md, section 9.\n",
        what, path);
    return false;
}

/* IDX headers store integers big-endian (most significant byte first);
 * read 4 bytes and assemble them regardless of the host's endianness. */
static bool read_be_u32(std::FILE *f, unsigned int &v) {
    v = 0;
    for (int i = 0; i < 4; i++) {
        int c = std::fgetc(f);
        if (c == EOF)
            return false;
        v = (v << 8) | static_cast<unsigned int>(c);
    }
    return true;
}

/* The real thing: IDX image file (magic 0x00000803: n x rows x cols bytes)
 * plus IDX label file (magic 0x00000801: n bytes). */
static bool load_idx(const char *img_path, const char *lbl_path, MnistData &out) {
    std::FILE *fi = std::fopen(img_path, "rb");
    if (!fi)
        return fail(img_path, "cannot open");
    std::FILE *fl = std::fopen(lbl_path, "rb");
    if (!fl) {
        std::fclose(fi);
        return fail(lbl_path, "cannot open");
    }

    unsigned int magic_i, n_i, rows, cols, magic_l, n_l;
    bool header_ok =
        read_be_u32(fi, magic_i) && read_be_u32(fi, n_i) &&
        read_be_u32(fi, rows) && read_be_u32(fi, cols) &&
        read_be_u32(fl, magic_l) && read_be_u32(fl, n_l) &&
        magic_i == 0x00000803u && magic_l == 0x00000801u &&
        n_i == n_l && rows == 28 && cols == 28;
    if (!header_ok) {
        std::fclose(fi); std::fclose(fl);
        return fail(img_path, "bad IDX header in (corrupt or wrong file?)");
    }

    out.n = static_cast<int>(n_i);
    out.rows = static_cast<int>(rows);
    out.cols = static_cast<int>(cols);
    size_t n_pix = static_cast<size_t>(out.n) * out.rows * out.cols;

    std::vector<unsigned char> raw(n_pix);
    out.labels.resize(out.n);
    bool body_ok =
        std::fread(raw.data(), 1, n_pix, fi) == n_pix &&
        std::fread(out.labels.data(), 1, out.n, fl) == static_cast<size_t>(out.n);
    std::fclose(fi);
    std::fclose(fl);
    if (!body_ok)
        return fail(img_path, "truncated data in");

    out.images.resize(n_pix);
    for (size_t k = 0; k < n_pix; k++)  /* pixel_k = byte_k / 255, so 0..1 */
        out.images[k] = raw[k] / 255.0;
    return true;
}

/* CSV fallback (SRS section 6): one image per line, "label,p0,...,p783",
 * pixels 0..255.  Slower and bigger than IDX, but survives link rot. */
static bool load_csv(const char *csv_path, MnistData &out) {
    std::FILE *f = std::fopen(csv_path, "rb");
    if (!f)
        return fail(csv_path, "cannot open");

    out.rows = 28;
    out.cols = 28;
    std::vector<char> line(8192);
    while (std::fgets(line.data(), static_cast<int>(line.size()), f)) {
        char *p = line.data();
        long label = std::strtol(p, &p, 10);
        if (label < 0 || label > 9) {
            std::fclose(f);
            return fail(csv_path, "bad label (line must be label,p0,...,p783) in");
        }
        out.labels.push_back(static_cast<unsigned char>(label));
        for (int k = 0; k < 28 * 28; k++) {
            if (*p != ',') {
                std::fclose(f);
                return fail(csv_path, "expected 784 comma-separated pixels in");
            }
            long pix = std::strtol(p + 1, &p, 10);
            out.images.push_back(pix / 255.0);  /* pixel = value / 255 */
        }
    }
    std::fclose(f);

    out.n = static_cast<int>(out.labels.size());
    if (out.n == 0)
        return fail(csv_path, "no rows parsed from");
    return true;
}

bool mnist_load(const char *img_path, const char *lbl_path, MnistData &out) {
    size_t len = std::strlen(img_path);
    if (len >= 4 && std::strcmp(img_path + len - 4, ".csv") == 0)
        return load_csv(img_path, out);
    return load_idx(img_path, lbl_path, out);
}
