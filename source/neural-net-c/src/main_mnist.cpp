/* Stage 2 (SRS NN-5..NN-9): the SAME library code as XOR, scaled up to
 * classify MNIST digits: 784 -> 128 (ReLU) -> 10 (softmax), cross-entropy,
 * mini-batch SGD.
 *
 *   ./mnist                       train 10 epochs, report per epoch
 *   ./mnist --seed N              reproducible run (default seed 42)
 *   ./mnist --save w.bin          train, then save weights
 *   ./mnist --load w.bin --eval   no training: load weights, print accuracy
 *   ./mnist --load w.bin --predict 7   show test image 7 as ASCII art
 */
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <vector>
#include "nn.hpp"
#include "loss.hpp"
#include "data_mnist.hpp"

static const int    EPOCHS = 10;
static const int    BATCH = 64;
static const double ETA = 0.1;
static const int    N_IN = 784, N_HID = 128, N_OUT = 10;

/* Share of test images whose argmax(a) equals the label. */
static double evaluate(Network &net, const MnistData &test) {
    int correct = 0;
    std::vector<double> x(N_IN);
    for (int s = 0; s < test.n; s++) {
        std::memcpy(x.data(), &test.images[static_cast<size_t>(s) * N_IN],
                    N_IN * sizeof(double));
        const std::vector<double> &a = net.forward(x);
        int best = 0;
        for (int j = 1; j < N_OUT; j++)  /* argmax_j a_j */
            if (a[j] > a[best])
                best = j;
        if (best == test.labels[s])
            correct++;
    }
    return 100.0 * correct / test.n;
}

/* Mini-batch SGD (SRS 1.3-8): shuffle, then for each batch accumulate the
 * per-sample gradients (backward) and apply one averaged update. */
static void train(Network &net, const MnistData &train_d, const MnistData &test_d) {
    std::vector<int> idx(train_d.n);
    for (int i = 0; i < train_d.n; i++)
        idx[i] = i;

    std::vector<double> x(N_IN), y(N_OUT, 0.0), delta(N_OUT);
    std::clock_t t0 = std::clock();

    for (int epoch = 1; epoch <= EPOCHS; epoch++) {
        for (int i = train_d.n - 1; i > 0; i--) {   /* Fisher-Yates shuffle */
            int j = static_cast<int>(nn_rand_u32() % (i + 1));
            int t = idx[i]; idx[i] = idx[j]; idx[j] = t;
        }

        double epoch_loss = 0.0;
        for (int start = 0; start < train_d.n; start += BATCH) {
            int batch_n = (start + BATCH <= train_d.n) ? BATCH : train_d.n - start;
            for (int k = 0; k < batch_n; k++) {
                int s = idx[start + k];
                std::memcpy(x.data(), &train_d.images[static_cast<size_t>(s) * N_IN],
                            N_IN * sizeof(double));
                y[train_d.labels[s]] = 1.0;         /* one-hot target */

                const std::vector<double> &a = net.forward(x);
                epoch_loss += cross_entropy(a, y);
                softmax_ce_delta(a, y, delta);      /* delta = a - y */
                net.backward(x, delta);             /* gradients accumulate */

                y[train_d.labels[s]] = 0.0;         /* reset one-hot */
            }
            net.update(ETA, batch_n);               /* one averaged SGD step */
        }

        double secs = static_cast<double>(std::clock() - t0) / CLOCKS_PER_SEC;
        std::printf("epoch %2d  train_loss %.4f  test_acc %.2f%%  elapsed %.1fs\n",
                    epoch, epoch_loss / train_d.n, evaluate(net, test_d), secs);
    }
}

/* ---------- weight save/load (SRS NN-8) ----------
 * Format: "NNC1" magic, int32 n_layers, then per layer int32 in,out,act
 * followed by the raw doubles of W and b.  Native little-endian; meant for
 * reloading on the same machine, not for interchange. */

static bool save_weights(const Network &net, const char *path) {
    std::FILE *f = std::fopen(path, "wb");
    if (!f) {
        std::fprintf(stderr, "error: cannot write '%s'\n", path);
        return false;
    }
    std::fwrite("NNC1", 1, 4, f);
    int n_layers = static_cast<int>(net.layers.size());
    std::fwrite(&n_layers, sizeof(int), 1, f);
    for (const Layer &ly : net.layers) {
        int act = static_cast<int>(ly.act);
        std::fwrite(&ly.in, sizeof(int), 1, f);
        std::fwrite(&ly.out, sizeof(int), 1, f);
        std::fwrite(&act, sizeof(int), 1, f);
        std::fwrite(ly.W.data(), sizeof(double), ly.W.size(), f);
        std::fwrite(ly.b.data(), sizeof(double), ly.b.size(), f);
    }
    std::fclose(f);
    std::printf("weights saved to %s\n", path);
    return true;
}

static bool load_weights(Network &net, const char *path) {
    std::FILE *f = std::fopen(path, "rb");
    if (!f) {
        std::fprintf(stderr, "error: cannot open '%s' (train with --save first)\n", path);
        return false;
    }
    char magic[4];
    int n_layers = 0;
    bool ok = std::fread(magic, 1, 4, f) == 4 &&
              std::memcmp(magic, "NNC1", 4) == 0 &&
              std::fread(&n_layers, sizeof(int), 1, f) == 1 &&
              n_layers == static_cast<int>(net.layers.size());
    for (Layer &ly : net.layers) {
        int in = 0, out = 0, act = -1;
        ok = ok && std::fread(&in, sizeof(int), 1, f) == 1 &&
                   std::fread(&out, sizeof(int), 1, f) == 1 &&
                   std::fread(&act, sizeof(int), 1, f) == 1 &&
                   in == ly.in && out == ly.out && act == static_cast<int>(ly.act) &&
                   std::fread(ly.W.data(), sizeof(double), ly.W.size(), f) == ly.W.size() &&
                   std::fread(ly.b.data(), sizeof(double), ly.b.size(), f) == ly.b.size();
        if (!ok)
            break;
    }
    std::fclose(f);
    if (!ok)
        std::fprintf(stderr, "error: '%s' is not a valid 784-128-10 weight file\n", path);
    return ok;
}

/* Print one test image as ASCII art with predicted vs true label (NN-8). */
static void predict_one(Network &net, const MnistData &test, int s) {
    static const char RAMP[] = " .:-=+*#%@";   /* 10 gray levels, dark = ink */
    std::vector<double> x(N_IN);
    std::memcpy(x.data(), &test.images[static_cast<size_t>(s) * N_IN],
                N_IN * sizeof(double));

    for (int r = 0; r < test.rows; r++) {
        for (int c = 0; c < test.cols; c++)   /* ramp index = pixel * 9.99 */
            std::putchar(RAMP[static_cast<int>(x[r * test.cols + c] * 9.99)]);
        std::putchar('\n');
    }

    const std::vector<double> &a = net.forward(x);
    int best = 0;
    for (int j = 1; j < N_OUT; j++)
        if (a[j] > a[best])
            best = j;
    std::printf("predicted: %d   true: %d\n", best, test.labels[s]);
}

struct Options {
    unsigned int seed = 42;   /* fixed default seed (NN-7) */
    const char *save_path = NULL, *load_path = NULL;
    int predict_idx = -1;
    bool do_eval = false;
};

static bool parse_args(int argc, char **argv, Options &opt) {
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--seed") == 0 && i + 1 < argc)
            opt.seed = static_cast<unsigned int>(std::strtoul(argv[++i], NULL, 10));
        else if (std::strcmp(argv[i], "--save") == 0 && i + 1 < argc)
            opt.save_path = argv[++i];
        else if (std::strcmp(argv[i], "--load") == 0 && i + 1 < argc)
            opt.load_path = argv[++i];
        else if (std::strcmp(argv[i], "--eval") == 0)
            opt.do_eval = true;
        else if (std::strcmp(argv[i], "--predict") == 0 && i + 1 < argc)
            opt.predict_idx = std::atoi(argv[++i]);
        else {
            std::fprintf(stderr, "usage: mnist [--seed N] [--save FILE] "
                                 "[--load FILE] [--eval] [--predict INDEX]\n");
            return false;
        }
    }
    return true;
}

int main(int argc, char **argv) {
    Options opt;
    if (!parse_args(argc, argv, opt))
        return 1;

    MnistData test;
    if (!mnist_load("data/t10k-images-idx3-ubyte", "data/t10k-labels-idx1-ubyte", test))
        return 1;

    Network net({N_IN, N_HID, N_OUT}, {Activation::Relu, Activation::Softmax}, opt.seed);

    if (opt.load_path) {                   /* inference only, no training */
        if (!load_weights(net, opt.load_path))
            return 1;
        if (opt.predict_idx >= 0) {
            if (opt.predict_idx >= test.n) {
                std::fprintf(stderr, "error: --predict index must be 0..%d\n", test.n - 1);
                return 1;
            }
            predict_one(net, test, opt.predict_idx);
        }
        if (opt.do_eval || opt.predict_idx < 0)
            std::printf("test_acc %.2f%% (%d images)\n", evaluate(net, test), test.n);
        return 0;
    }

    MnistData train_d;
    if (!mnist_load("data/train-images-idx3-ubyte", "data/train-labels-idx1-ubyte", train_d))
        return 1;
    std::printf("MNIST loaded: %d train / %d test images (%dx%d)\n",
                train_d.n, test.n, train_d.rows, train_d.cols);

    train(net, train_d, test);

    if (opt.save_path && !save_weights(net, opt.save_path))
        return 1;
    return 0;
}
