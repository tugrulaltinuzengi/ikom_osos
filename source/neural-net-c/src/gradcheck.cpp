#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>
#include "nn.hpp"
#include "activations.hpp"
#include "loss.hpp"

static const double EPS = 1e-5;           /* central-difference step size */
static const double REL_THRESHOLD = 1e-4; /* max allowed relative error (SRS NN-4) */

/* Function-pointer shapes so one gradcheck routine serves both configs.
 * mse() and cross_entropy() already match LossFn's signature exactly. */
typedef double (*LossFn)(const std::vector<double> &a, const std::vector<double> &y);
typedef void (*DeltaFn)(const std::vector<double> &a, const std::vector<double> &z,
                        const std::vector<double> &y, std::vector<double> &delta_out);

/* Stage 1 output delta: delta_j = mse_prime(a_j,y_j,n) * sigmoid_prime(z_j) */
static void delta_mse_sigmoid(const std::vector<double> &a, const std::vector<double> &z,
                              const std::vector<double> &y, std::vector<double> &delta_out) {
    int n = static_cast<int>(a.size());
    for (int j = 0; j < n; j++)
        delta_out[j] = mse_prime(a[j], y[j], n) * sigmoid_prime(z[j]);
}

/* Stage 2 output delta: delta_j = a_j - y_j (softmax + cross-entropy) */
static void delta_softmax_ce(const std::vector<double> &a, const std::vector<double> &z,
                             const std::vector<double> &y, std::vector<double> &delta_out) {
    (void) z; /* softmax's combined shortcut does not need z */
    softmax_ce_delta(a, y, delta_out);
}

/* Plain sanity asserts on the building blocks (Tasks 1-2), before trusting
 * them inside the gradient check itself. */
static void sanity_checks() {
    assert(sigmoid(0.0) == 0.5);
    assert(relu(-3.0) == 0.0 && relu(2.0) == 2.0);

    std::vector<double> z = {1.0, 2.0, 3.0};
    std::vector<double> a(3);
    softmax(z, a);
    assert(std::fabs((a[0] + a[1] + a[2]) - 1.0) < 1e-12);
    assert(a[0] < a[1] && a[1] < a[2]); /* strictly increasing, since z is */

    std::vector<double> v = {0.3, 0.7};
    assert(mse(v, v) == 0.0); /* equal vectors -> zero loss */

    std::printf("sanity checks: PASS\n");
}

/* Numerically differentiate the loss w.r.t. each parameter in p[] via
 * centered finite differences, compare against the saved analytical
 * gradient g_ana[], and return the max relative error found. */
static double check_param_array(std::vector<double> &p, const std::vector<double> &g_ana,
                                Network &net, const std::vector<double> &x,
                                const std::vector<double> &y, LossFn loss_fn) {
    double max_rel = 0.0;
    for (size_t k = 0; k < p.size(); k++) {
        double save = p[k];
        p[k] = save + EPS;                          /* L(w + eps) */
        double Lp = loss_fn(net.forward(x), y);
        p[k] = save - EPS;                          /* L(w - eps) */
        double Lm = loss_fn(net.forward(x), y);
        p[k] = save;                                /* restore */

        double g_num = (Lp - Lm) / (2.0 * EPS);     /* central difference */
        double rel = std::fabs(g_ana[k] - g_num)
                   / std::fmax(1e-8, std::fabs(g_ana[k]) + std::fabs(g_num));
        if (rel > max_rel)
            max_rel = rel;
    }
    return max_rel;
}

/* Run one full gradient check: analytical forward+backward, save dW/db
 * aside, then numerically check every W and b entry of every layer against
 * that saved copy.  Prints the result and returns the max relative error. */
static double gradcheck_config(const char *name, Network &net, const std::vector<double> &x,
                               const std::vector<double> &y, LossFn loss_fn, DeltaFn delta_fn) {
    int L = static_cast<int>(net.layers.size());

    const std::vector<double> &a_out = net.forward(x); /* analytical: fresh forward */
    std::vector<double> delta_out(net.layers[L-1].out);
    delta_fn(a_out, net.layers[L-1].z, y, delta_out);
    net.backward(x, delta_out);                        /* + backward */

    double max_rel = 0.0;
    for (int l = 0; l < L; l++) {
        Layer &ly = net.layers[l];

        std::vector<double> dW_saved = ly.dW; /* copy analytical grads aside */
        std::vector<double> db_saved = ly.db;

        double relW = check_param_array(ly.W, dW_saved, net, x, y, loss_fn);
        double relb = check_param_array(ly.b, db_saved, net, x, y, loss_fn);
        if (relW > max_rel) max_rel = relW;
        if (relb > max_rel) max_rel = relb;
    }

    bool pass = max_rel < REL_THRESHOLD;
    std::printf("%s: max relative error = %.1e  %s\n", name, max_rel, pass ? "PASS" : "FAIL");
    return max_rel;
}

int main() {
    sanity_checks();
    bool fail = false;

    /* Config A: sizes {2,3,2}, sigmoid-sigmoid hidden/output, MSE loss. */
    {
        Network net({2, 3, 2}, {Activation::Sigmoid, Activation::Sigmoid}, 42);

        nn_seed(123); /* independent, fixed stream for input/target */
        std::vector<double> x(2), y(2);
        for (int i = 0; i < 2; i++) x[i] = nn_uniform(-1.0, 1.0);
        for (int i = 0; i < 2; i++) y[i] = nn_uniform(0.0, 1.0);

        double rel = gradcheck_config("config A (2-3-2 sigmoid, MSE)",
                                      net, x, y, mse, delta_mse_sigmoid);
        if (rel >= REL_THRESHOLD) fail = true;
    }

    /* Config B: sizes {4,6,3}, relu hidden / softmax output, cross-entropy. */
    {
        Network net({4, 6, 3}, {Activation::Relu, Activation::Softmax}, 7);

        nn_seed(99); /* independent, fixed stream for input/target */
        std::vector<double> x(4);
        for (int i = 0; i < 4; i++) x[i] = nn_uniform(-1.0, 1.0);
        std::vector<double> y = {0.0, 1.0, 0.0}; /* one-hot target: class 1 */

        double rel = gradcheck_config("config B (4-6-3 relu-softmax, CE)",
                                      net, x, y, cross_entropy, delta_softmax_ce);
        if (rel >= REL_THRESHOLD) fail = true;
    }

    if (fail) {
        std::printf("GRADCHECK FAIL\n");
        return 1;
    }
    std::printf("GRADCHECK PASS\n");
    return 0;
}
