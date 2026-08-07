#ifndef NN_HPP
#define NN_HPP

#include <vector>

enum class Activation { Sigmoid, Relu, Softmax };

/* One fully-connected layer (SRS 1.3-1).  Every vector is sized exactly once
 * in the Network constructor and freed automatically when the Network is
 * destroyed — RAII is the C++ form of NR-5 (allocate once, free once, sizes
 * visible here).  Row-major: W[j*in + i] is the weight from input i to
 * neuron j. */
struct Layer {
    int in = 0, out = 0;
    std::vector<double> W;      /* out*in  weights                          */
    std::vector<double> b;      /* out     biases                           */
    std::vector<double> z;      /* out     cache: pre-activation, z = Wx+b  */
    std::vector<double> a;      /* out     cache: activation,     a = f(z)  */
    std::vector<double> delta;  /* out     cache: dL/dz                     */
    std::vector<double> dW;     /* out*in  gradient accumulator dL/dW       */
    std::vector<double> db;     /* out     gradient accumulator dL/db       */
    Activation act = Activation::Sigmoid;
};

/* Reproducible PRNG (xorshift32) — NOT std::mt19937 + distributions, whose
 * floating-point output the C++ standard does not pin down across library
 * implementations.  With our own generator, --seed N gives bit-for-bit
 * identical runs everywhere (NN-7). */
void         nn_seed(unsigned int s);
unsigned int nn_rand_u32();
double       nn_uniform(double lo, double hi);

struct Network {
    std::vector<Layer> layers;

    /* sizes = {n_in, h1, ..., n_out}; acts has one entry per layer, so
     * acts.size() == sizes.size() - 1. */
    Network(const std::vector<int> &sizes, const std::vector<Activation> &acts,
            unsigned int seed);

    /* Forward pass: input -> layer by layer -> output (returns last a). */
    const std::vector<double> &forward(const std::vector<double> &x);

    /* Backprop: caller supplies delta_out = dL/dz of the OUTPUT layer;
     * gradients accumulate into each layer's dW/db. */
    void backward(const std::vector<double> &x, const std::vector<double> &delta_out);

    /* Plain SGD: w <- w - eta * dL/dw, gradients averaged over batch_size
     * and then cleared. */
    void update(double eta, int batch_size);
};

#endif
