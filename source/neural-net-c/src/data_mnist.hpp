#ifndef DATA_MNIST_HPP
#define DATA_MNIST_HPP

#include <vector>

struct MnistData {
    int n = 0;                          /* number of samples          */
    int rows = 0, cols = 0;             /* 28 x 28                    */
    std::vector<double> images;         /* n*rows*cols, scaled 0..1   */
    std::vector<unsigned char> labels;  /* n, values 0..9             */
};

/* Loads an IDX image+label file pair (magic 0x00000803 / 0x00000801,
 * big-endian header).  If img_path ends in ".csv", parses the CSV fallback
 * instead (one "label,p0,...,p783" line per image; lbl_path is ignored).
 * Returns true on success; on any failure prints a clear ASCII error WITH
 * download instructions (SRS NN-9) and returns false — never crashes. */
bool mnist_load(const char *img_path, const char *lbl_path, MnistData &out);

#endif
