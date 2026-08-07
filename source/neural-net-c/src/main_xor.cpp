/* Stage 1 (SRS NN-2, NN-3, NN-7): a 2-4-1 sigmoid MLP learns XOR.
 *
 *   ./xor            train until epoch-mean MSE < 0.01, print truth table
 *   ./xor --trace    print EVERY number of one training step, then exit
 *   ./xor --seed N   reproducible run with a different seed (default 42)
 */
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "nn.hpp"
#include "activations.hpp"
#include "loss.hpp"

static const double ETA = 0.5;        /* learning rate */
static const int    MAX_EPOCHS = 20000;
static const double TARGET_MSE = 0.01; /* NN-2 stop criterion */

/* The 4 rows of the XOR truth table. */
static const double XOR_X[4][2] = {{0,0}, {0,1}, {1,0}, {1,1}};
static const double XOR_Y[4]    = {0, 1, 1, 0};

/* Output-layer delta for Stage 1, the chain rule visible at the call site:
 * delta_j = dL/da_j * da_j/dz_j = mse_prime(a_j,y_j,n) * sigmoid_prime(z_j) */
static void output_delta(const Network &net, const std::vector<double> &y,
                         std::vector<double> &delta) {
    const Layer &out = net.layers.back();
    int n = out.out;
    for (int j = 0; j < n; j++)
        delta[j] = mse_prime(out.a[j], y[j], n) * sigmoid_prime(out.z[j]);
}

/* One epoch of per-sample SGD over the 4 XOR rows in shuffled order
 * (SRS 1.3-8).  Returns the epoch-mean MSE. */
static double train_epoch(Network &net) {
    int idx[4] = {0, 1, 2, 3};
    for (int i = 3; i > 0; i--) {          /* Fisher-Yates shuffle */
        int j = static_cast<int>(nn_rand_u32() % (i + 1));
        int t = idx[i]; idx[i] = idx[j]; idx[j] = t;
    }

    double epoch_mse = 0.0;
    std::vector<double> delta(1);
    for (int s = 0; s < 4; s++) {
        std::vector<double> x = {XOR_X[idx[s]][0], XOR_X[idx[s]][1]};
        std::vector<double> y = {XOR_Y[idx[s]]};

        const std::vector<double> &a = net.forward(x);
        epoch_mse += mse(a, y);
        output_delta(net, y, delta);
        net.backward(x, delta);
        net.update(ETA, 1);                /* plain SGD, batch of one */
    }
    return epoch_mse / 4.0;
}

static void print_truth_table(Network &net) {
    std::printf("\n x1 x2 | predicted | target\n");
    for (int s = 0; s < 4; s++) {
        std::vector<double> x = {XOR_X[s][0], XOR_X[s][1]};
        const std::vector<double> &a = net.forward(x);
        std::printf("  %.0f  %.0f |   %.4f  |   %.0f\n",
                    x[0], x[1], a[0], XOR_Y[s]);
    }
}

/* ---------- --trace mode (NN-3): one hand-checkable training step ---------- */

static void trace_params(const Network &net, const char *title) {
    std::printf("--- %s ---\n", title);
    for (size_t l = 0; l < net.layers.size(); l++) {
        const Layer &ly = net.layers[l];
        int ln = static_cast<int>(l) + 1;  /* 1-based layer names: W1, W2 */
        for (int j = 0; j < ly.out; j++)
            for (int i = 0; i < ly.in; i++)
                std::printf("W%d_%d%d = %+.6f%s", ln, j, i, ly.W[j * ly.in + i],
                            (i == ly.in - 1) ? "\n" : "   ");
        for (int j = 0; j < ly.out; j++)
            std::printf("b%d_%d  = %+.6f\n", ln, j, ly.b[j]);
    }
}

/* Forward pass with every z_j and a_j spelled out term by term. */
static void trace_forward(Network &net, const std::vector<double> &x) {
    std::printf("--- forward pass: z_j = sum_i W_ji*in_i + b_j, a_j = sigmoid(z_j) ---\n");
    net.forward(x);
    for (size_t l = 0; l < net.layers.size(); l++) {
        const Layer &ly = net.layers[l];
        const std::vector<double> &in = (l == 0) ? x : net.layers[l-1].a;
        int ln = static_cast<int>(l) + 1;
        for (int j = 0; j < ly.out; j++) {
            std::printf("z%d_%d = ", ln, j);
            for (int i = 0; i < ly.in; i++)      /* W_ji * in_i terms */
                std::printf("(%+.6f)*(%.6f) + ", ly.W[j * ly.in + i], in[i]);
            std::printf("(%+.6f) = %+.6f\n", ly.b[j], ly.z[j]);
            std::printf("a%d_%d = sigmoid(%+.6f) = %.6f\n", ln, j, ly.z[j], ly.a[j]);
        }
    }
}

/* Loss, output delta and hidden deltas, every number shown. */
static void trace_backward(Network &net, const std::vector<double> &x,
                           const std::vector<double> &y) {
    const Layer &out = net.layers[1];
    double a2 = out.a[0], z2 = out.z[0];

    std::printf("--- loss: L = (a2_0 - y)^2 ---\n");
    std::printf("L = (%.6f - %.0f)^2 = %.6f\n", a2, y[0], (a2-y[0])*(a2-y[0]));
    std::printf("dL/da2_0 = 2*(a2_0 - y)/1 = %+.6f\n", mse_prime(a2, y[0], 1));

    std::printf("--- backward pass: deltas (chain rule) ---\n");
    std::vector<double> delta = {mse_prime(a2, y[0], 1) * sigmoid_prime(z2)};
    std::printf("delta2_0 = dL/da2_0 * sigmoid'(z2_0) = %+.6f * %.6f = %+.6f\n",
                mse_prime(a2, y[0], 1), sigmoid_prime(z2), delta[0]);
    net.backward(x, delta);

    const Layer &hid = net.layers[0];
    for (int j = 0; j < hid.out; j++)   /* delta1_j = W2_0j * delta2_0 * s'(z1_j) */
        std::printf("delta1_%d = W2_0%d * delta2_0 * sigmoid'(z1_%d) "
                    "= %+.6f * %+.6f * %.6f = %+.6f\n",
                    j, j, j, out.W[j], delta[0],
                    sigmoid_prime(hid.z[j]), hid.delta[j]);

    std::printf("--- gradients: dW_ji = delta_j * input_i, db_j = delta_j ---\n");
    for (int j = 0; j < out.out; j++) {
        for (int i = 0; i < out.in; i++)
            std::printf("dW2_%d%d = delta2_%d * a1_%d = %+.6f\n",
                        j, i, j, i, out.dW[j * out.in + i]);
        std::printf("db2_%d  = delta2_%d = %+.6f\n", j, j, out.db[j]);
    }
    for (int j = 0; j < hid.out; j++) {
        for (int i = 0; i < hid.in; i++)
            std::printf("dW1_%d%d = delta1_%d * x_%d = %+.6f\n",
                        j, i, j, i, hid.dW[j * hid.in + i]);
        std::printf("db1_%d  = delta1_%d = %+.6f\n", j, j, hid.db[j]);
    }
}

/* Apply the SGD update and print old -> new for every parameter. */
static void trace_update(Network &net) {
    std::printf("--- update: w <- w - eta*grad  (eta = %.1f) ---\n", ETA);
    std::vector<std::vector<double>> oldW, oldb, grW, grb;
    for (const Layer &ly : net.layers) {
        oldW.push_back(ly.W);  oldb.push_back(ly.b);
        grW.push_back(ly.dW);  grb.push_back(ly.db);  /* update() clears these */
    }
    net.update(ETA, 1);
    for (size_t l = 0; l < net.layers.size(); l++) {
        const Layer &ly = net.layers[l];
        int ln = static_cast<int>(l) + 1;
        for (int j = 0; j < ly.out; j++) {
            for (int i = 0; i < ly.in; i++)
                std::printf("W%d_%d%d: %+.6f - %.1f*%+.6f = %+.6f\n", ln, j, i,
                            oldW[l][j * ly.in + i], ETA, grW[l][j * ly.in + i],
                            ly.W[j * ly.in + i]);
            std::printf("b%d_%d : %+.6f - %.1f*%+.6f = %+.6f\n", ln, j,
                        oldb[l][j], ETA, grb[l][j], ly.b[j]);
        }
    }
}

/* One full training step on sample (1,0)->1, every number printed so it can
 * be checked by hand on paper (SRS NN-3 - the core learning tool). */
static void run_trace(Network &net) {
    std::vector<double> x = {1.0, 0.0};
    std::vector<double> y = {1.0};
    std::printf("=== ONE TRAINING STEP, sample x=(1,0) -> y=1 ===\n\n");
    trace_params(net, "initial parameters");
    trace_forward(net, x);
    trace_backward(net, x, y);
    trace_update(net);
    std::printf("\n=== end of step: this is what happens 4x per epoch ===\n");
}

int main(int argc, char **argv) {
    unsigned int seed = 42;    /* fixed default seed (NN-7) */
    bool trace = false;
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--trace") == 0)
            trace = true;
        else if (std::strcmp(argv[i], "--seed") == 0 && i + 1 < argc)
            seed = static_cast<unsigned int>(std::strtoul(argv[++i], NULL, 10));
        else {
            std::fprintf(stderr, "usage: xor [--seed N] [--trace]\n");
            return 1;
        }
    }

    Network net({2, 4, 1}, {Activation::Sigmoid, Activation::Sigmoid}, seed);

    if (trace) {           /* --trace is XOR-only by design (SRS section 6) */
        run_trace(net);
        return 0;
    }

    for (int epoch = 1; epoch <= MAX_EPOCHS; epoch++) {
        double m = train_epoch(net);
        if (epoch % 1000 == 0)
            std::printf("epoch %5d  mse %.6f\n", epoch, m);
        if (m < TARGET_MSE) {
            std::printf("converged: epoch %d  mse %.6f < %.2f\n", epoch, m, TARGET_MSE);
            break;
        }
    }
    print_truth_table(net);
    return 0;
}
