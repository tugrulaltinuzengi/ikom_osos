#include <cmath>
#include <cstdio>
#include <cstdlib>
#include "nn.hpp"
#include "activations.hpp"

/* --- Reproducible PRNG: xorshift32 (Marsaglia) --- */
static unsigned int rng_state = 1;

/* Seed the generator.  xorshift32 is stuck at 0 forever if the state is
 * ever 0 (0 XOR anything shifted is still 0), so seed 0 is remapped to a
 * fixed nonzero constant. */
void nn_seed(unsigned int s) {
    rng_state = (s == 0) ? 0x9e3779b9u : s;
}

/* One xorshift32 step (Marsaglia's "xor-shift" generator). */
unsigned int nn_rand_u32() {
    unsigned int x = rng_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    rng_state = x;
    return x;
}

/* Map a uniform u32 draw into [lo, hi). */
double nn_uniform(double lo, double hi) {
    double u = nn_rand_u32() / 4294967296.0; /* u32 / 2^32, so u in [0,1) */
    return lo + u * (hi - lo);
}

/* Size one layer's vectors (allocated exactly once here, NR-5) and
 * initialize its weights.
 *
 * Xavier init (sigmoid/softmax layers): s = sqrt(6/(in+out)).  Drawing
 * W ~ uniform(-s, s) keeps the variance of a layer's output roughly equal
 * to the variance of its input, so signals neither shrink to zero nor grow
 * without bound as they pass through many layers (SRS 1.3-9).
 *
 * He init (ReLU layers): s = sqrt(2/in).  ReLU zeroes out about half of
 * its inputs, which would otherwise halve the output variance at every
 * layer; doubling the Xavier-style variance (2/in instead of 1/in)
 * compensates for that loss. */
static void layer_init(Layer &ly, int in, int out, Activation act) {
    ly.in = in;
    ly.out = out;
    ly.act = act;

    ly.W.resize(static_cast<size_t>(out) * in);
    ly.b.assign(out, 0.0);
    ly.z.assign(out, 0.0);
    ly.a.assign(out, 0.0);
    ly.delta.assign(out, 0.0);
    ly.dW.assign(static_cast<size_t>(out) * in, 0.0);
    ly.db.assign(out, 0.0);

    double s = (act == Activation::Relu) ? std::sqrt(2.0 / in)
                                         : std::sqrt(6.0 / (in + out));
    for (int j = 0; j < out; j++)      /* W_ji ~ uniform(-s, s) */
        for (int i = 0; i < in; i++)
            ly.W[j * in + i] = nn_uniform(-s, s);
}

/* Build the network: one Layer per (sizes[l] -> sizes[l+1]) transition. */
Network::Network(const std::vector<int> &sizes, const std::vector<Activation> &acts,
                 unsigned int seed) {
    nn_seed(seed);

    int n_layers = static_cast<int>(acts.size());
    for (int l = 0; l < n_layers - 1; l++)      /* softmax's hidden-delta rule */
        if (acts[l] == Activation::Softmax) {   /* does not apply, so reject it */
            std::fprintf(stderr, "Network: Activation::Softmax is only valid on "
                                 "the output layer (layer %d is hidden)\n", l);
            std::exit(1);
        }

    layers.resize(n_layers);
    for (int l = 0; l < n_layers; l++)
        layer_init(layers[l], sizes[l], sizes[l + 1], acts[l]);
}

/* Forward pass (SRS 1.3-2, 1.3-4): input -> layer by layer -> output. */
const std::vector<double> &Network::forward(const std::vector<double> &x) {
    const std::vector<double> *in = &x;
    for (size_t l = 0; l < layers.size(); l++) {
        Layer &ly = layers[l];
        for (int j = 0; j < ly.out; j++) {   /* z_j = sum_i W_ji * in_i + b_j */
            double z = ly.b[j];
            for (int i = 0; i < ly.in; i++)
                z += ly.W[j * ly.in + i] * (*in)[i];
            ly.z[j] = z;
        }
        if (ly.act == Activation::Softmax)
            softmax(ly.z, ly.a);              /* vector activation */
        else
            for (int j = 0; j < ly.out; j++)  /* a_j = f(z_j) */
                ly.a[j] = (ly.act == Activation::Relu) ? relu(ly.z[j])
                                                       : sigmoid(ly.z[j]);
        in = &ly.a;
    }
    return *in;
}

/* Backpropagation (SRS 1.3-6): the chain rule written out.
 * Caller supplies delta_out = dL/dz of the OUTPUT layer:
 *   Stage 1 (MSE+sigmoid):    delta_j = mse_prime(a_j,y_j,n) * sigmoid_prime(z_j)
 *   Stage 2 (CE+softmax):     delta_j = a_j - y_j   (softmax_ce_delta)
 * Gradients ACCUMULATE into dW/db so mini-batches just call this per sample;
 * update() averages and clears. */
void Network::backward(const std::vector<double> &x, const std::vector<double> &delta_out) {
    int L = static_cast<int>(layers.size());
    for (int j = 0; j < layers[L-1].out; j++)
        layers[L-1].delta[j] = delta_out[j];

    /* hidden deltas: delta^l = (W^{l+1}^T delta^{l+1}) (.) f'(z^l) */
    for (int l = L - 2; l >= 0; l--) {
        Layer &cur = layers[l], &nxt = layers[l+1];
        for (int j = 0; j < cur.out; j++) {
            double sum = 0.0;                 /* sum_k W^{l+1}_kj * delta^{l+1}_k */
            for (int k = 0; k < nxt.out; k++)
                sum += nxt.W[k * nxt.in + j] * nxt.delta[k];
            cur.delta[j] = sum * ((cur.act == Activation::Relu)
                                  ? relu_prime(cur.z[j])
                                  : sigmoid_prime(cur.z[j]));
        }
    }

    /* gradients: dL/dW^l_ji = delta^l_j * a^{l-1}_i,  dL/db^l_j = delta^l_j */
    for (int l = 0; l < L; l++) {
        Layer &ly = layers[l];
        const std::vector<double> &a_prev = (l == 0) ? x : layers[l-1].a;
        for (int j = 0; j < ly.out; j++) {
            for (int i = 0; i < ly.in; i++)
                ly.dW[j * ly.in + i] += ly.delta[j] * a_prev[i];
            ly.db[j] += ly.delta[j];
        }
    }
}

/* Parameter update (SRS 1.3-7): plain SGD  w <- w - eta * dL/dw.
 * Accumulated gradients are averaged over batch_size, then cleared. */
void Network::update(double eta, int batch_size) {
    for (size_t l = 0; l < layers.size(); l++) {
        Layer &ly = layers[l];
        for (int j = 0; j < ly.out; j++) {
            for (int i = 0; i < ly.in; i++) {
                ly.W[j * ly.in + i] -= eta * ly.dW[j * ly.in + i] / batch_size;
                ly.dW[j * ly.in + i] = 0.0;
            }
            ly.b[j] -= eta * ly.db[j] / batch_size;
            ly.db[j] = 0.0;
        }
    }
}
