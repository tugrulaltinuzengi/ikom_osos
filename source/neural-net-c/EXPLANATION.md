# EXPLANATION — the math behind `neural_net_c`, and where each piece lives in the code

This is the textbook half of the project (SRS NR-7). Read it side by side with
the source: every section ends with a pointer **-> code:** naming the exact
function, file, and lines that implement what the section just derived.

(This file explains the MATH. For a construct-by-construct explanation of the
CODE itself — every C++ feature, every library call, every file line by
line — see `CODE_WALKTHROUGH.md`.)

Notation used throughout (identical to the variable names in the code, NR-2):

| symbol | meaning | code |
|---|---|---|
| `x` | network input vector | `x` |
| `W^l_ji` | weight from neuron `i` of layer `l-1` to neuron `j` of layer `l` | `W[j*in + i]` |
| `b^l_j` | bias of neuron `j` in layer `l` | `b[j]` |
| `z^l_j` | pre-activation, `z = W*a + b` | `z[j]` |
| `a^l_j` | activation, `a = f(z)` | `a[j]` |
| `delta^l_j` | error signal `dL/dz^l_j` | `delta[j]` |
| `eta` | learning rate | `eta` |
| `L` | loss (MSE or cross-entropy) | `mse` / `cross_entropy` |

---

## 1. The perceptron: a weighted sum plus a bias

A single artificial neuron takes inputs `in_0..in_{n-1}`, multiplies each by
its own weight, adds a bias, and produces one number:

    z_j = sum_i ( W_ji * in_i ) + b_j

That is the whole neuron. Everything else in this project is bookkeeping to
run many of these in parallel (a layer) and in sequence (a network), and to
choose good values for `W` and `b` automatically (training).

**-> code:** the inner two loops of `Network::forward`, `src/nn.cpp` lines
88-93 (comment: `z_j = sum_i W_ji * in_i + b_j`).

## 2. Why hidden layers: XOR is not linearly separable

A single neuron (plus a threshold-ish activation) can only draw one straight
line through its input space and answer "which side are you on?". AND and OR
are like that. XOR is not — no single line separates its 1s from its 0s:

    x2
     1 |  1        0        outputs: (0,0)->0  (1,1)->0
       |                             (0,1)->1  (1,0)->1
     0 |  0        1
       +----------------- x1
          0        1

Try any line: it always puts one of the 1s with one of the 0s. The fix is a
**hidden layer**: layer 1 neurons each draw their own line, turning the input
into a new representation in which the classes *are* separable; the output
neuron then draws one line in that new space. This is the smallest example of
why deep networks work at all — layers build coordinates in which the problem
becomes easy. Our 2-4-1 network gives the hidden layer four lines to work
with, which is plenty for XOR.

**-> code:** the network shape `{2, 4, 1}` in `main`, `src/main_xor.cpp`
line 189; watch it learn with `./xor`.

## 3. The forward pass: layer by layer to an output

A `Layer` owns its weight matrix `W` (row-major, `out x in`), bias vector
`b`, and two caches filled in during the forward pass: `z` (pre-activation)
and `a` (activation). The caches are not an optimization — backprop (section
5) *needs* `z` and `a` of every layer, so we store them where they are
computed.

The forward pass is just the perceptron formula applied to every neuron of
every layer, feeding each layer's `a` into the next:

    a^0 = x
    z^l_j = sum_i ( W^l_ji * a^{l-1}_i ) + b^l_j
    a^l_j = f( z^l_j )              (f = the layer's activation function)

The output of the last layer is the network's answer.

**-> code:** `Layer` struct, `src/nn.hpp` lines 13-23; `Network::forward`,
`src/nn.cpp` lines 84-108.

## 4. Activation functions and their derivatives

Without a nonlinear `f`, stacking layers is pointless: a linear function of a
linear function is still linear, so any depth would collapse into one matrix.
The three activations used here, each written directly beside its derivative:

- **sigmoid** `s(z) = 1 / (1 + e^-z)` squashes into (0,1). Its derivative has
  the famous shortcut `s'(z) = s(z) * (1 - s(z))` — differentiate the
  quotient and the terms rearrange into s times (1-s).
- **ReLU** `r(z) = max(0, z)` and `r'(z) = 1 if z > 0 else 0`. Cheap, and its
  derivative does not vanish for positive inputs, which is why it trains deep
  nets faster than sigmoid (whose derivative peaks at only 0.25).
- **softmax** turns a whole vector of scores into probabilities:
  `a_j = e^{z_j} / sum_k e^{z_k}`. It is a *vector* activation — each output
  depends on every input — so it cannot be a per-neuron function like the
  other two. The code first subtracts `m = max(z)` from every entry; since
  `e^{z-m}/sum e^{z-m}` is algebraically identical, this changes nothing
  mathematically but keeps `exp` from overflowing (the max-subtraction trick).

**-> code:** `src/activations.cpp` — `sigmoid` lines 5-7, `sigmoid_prime`
10-13, `relu` 16-18, `relu_prime` 21-23, `softmax` 28-45.

## 5. Loss functions and backpropagation: the chain rule, written out

### 5.1 The two losses

Training needs a single number that says "how wrong is the network":

- **MSE** (Stage 1): `L = (1/n) * sum_j (a_j - y_j)^2`, with
  `dL/da_j = 2*(a_j - y_j)/n` — the derivative that starts backprop.
- **Cross-entropy** (Stage 2, over a softmax output): `L = -sum_j y_j*log(a_j)`
  where `y` is one-hot. It punishes confident wrong answers much harder than
  MSE does, which is what you want for classification.

**-> code:** `src/loss.cpp` — `mse` lines 5-13, `mse_prime` 16-18,
`cross_entropy` 21-31 (note the clamp that avoids `log(0)`).

### 5.2 The error signal delta

Define, for every neuron, `delta^l_j = dL/dz^l_j` — "if this neuron's
pre-activation changed a little, how much would the loss change?". Backprop
is nothing but computing all the deltas from last layer to first with the
chain rule, then reading the gradients off them.

**Output layer.** For sigmoid + MSE the chain is `L <- a <- z`:

    delta^L_j = dL/da_j * da_j/dz_j = mse_prime(a_j, y_j, n) * sigmoid_prime(z_j)

For softmax + cross-entropy something beautiful happens. Differentiating
softmax gives `da_k/dz_j = a_k * (1{k=j} - a_j)`, so

    dL/dz_j = sum_k (dL/da_k) * (da_k/dz_j)
            = sum_k ( -y_k / a_k ) * a_k * (1{k=j} - a_j)
            = -y_j + a_j * sum_k y_k
            = a_j - y_j            (one-hot y sums to 1)

All the fractions cancel: **delta = a - y**, the simplest formula in the
project. This is why softmax and cross-entropy are always used together, and
why `softmax` needs no standalone derivative in the code.

**Hidden layers.** Neuron `j` of layer `l` influences the loss only through
the neurons of layer `l+1`. Chain rule over all those paths:

    delta^l_j = ( sum_k W^{l+1}_kj * delta^{l+1}_k ) * f'(z^l_j)

i.e. take the next layer's deltas, send them backwards through the transposed
weights, and scale by the local activation slope.

**Gradients.** Since `z^l_j = sum_i W^l_ji * a^{l-1}_i + b^l_j`, each weight
and bias touches the loss only through its own `z`:

    dL/dW^l_ji = delta^l_j * a^{l-1}_i
    dL/db^l_j  = delta^l_j

That is the entire backpropagation algorithm.

**-> code:** output deltas at the call sites — `output_delta`,
`src/main_xor.cpp` lines 25-32 (MSE*sigmoid') and `softmax_ce_delta`,
`src/loss.cpp` lines 34-39 (a - y); hidden deltas and both gradient formulas
in `Network::backward`, `src/nn.cpp` lines 111-140.

## 6. Gradient checking: proving the backprop code is correct

Backprop bugs are silent — a wrong gradient still *decreases* the loss most
of the time, just badly. The antidote: the definition of a derivative. For
every single parameter `w` (temporarily nudged, everything else frozen):

    g_num = ( L(w + eps) - L(w - eps) ) / (2 * eps)        eps = 1e-5

The centered difference's error term is O(eps^2), so with doubles it agrees
with a *correct* analytical gradient to ~1e-8 relative error, while a typical
backprop bug (wrong sign, wrong index, missing factor) is wrong by orders of
magnitude. The check computes the relative error

    rel = |g_ana - g_num| / max(1e-8, |g_ana| + |g_num|)

for every W and b entry in two configurations (sigmoid+MSE and
relu+softmax+CE, so both delta formulas and all three activations are
exercised) and passes iff the max is below 1e-4 (SRS NN-4). Measured result:
~1e-9 on both configs — four orders of magnitude inside the bound.

**-> code:** `check_param_array`, `src/gradcheck.cpp` lines 54-75 (the
nudge-measure-restore loop); `gradcheck_config` lines 78-102; run `./gradcheck`.

## 7. Training: SGD, mini-batches, shuffling

Gradient descent updates every parameter a small step against its gradient:

    w <- w - eta * dL/dw

- **Stochastic** (Stage 1, XOR): compute gradients from *one* sample, update
  immediately. Noisy but effective for 4 samples.
- **Mini-batch** (Stage 2, MNIST): accumulate the gradients of 64 samples,
  update once with their *average*. The average is a better estimate of the
  true gradient, and one update per 64 samples is cheaper than 64 updates.
  In the code this falls out of the design for free: `backward()` always
  *accumulates* into `dW/db`, and `update(eta, batch_size)` divides by the
  batch size and clears the accumulators — call it after every sample (batch
  size 1) and you have SGD, call it after 64 and you have mini-batch.
- **Shuffling**: each epoch visits the training samples in a fresh random
  order (Fisher-Yates with our own PRNG), so batches do not repeat and the
  order teaches the network nothing spurious.

Reproducibility (SRS NN-7): all randomness — weight init and shuffles — comes
from one xorshift32 generator seeded by `--seed` (default 42), not from
`rand()` or `std::mt19937` distributions whose exact output the standards
leave to the implementation. Same seed, same run, bit for bit.

**-> code:** `Network::update`, `src/nn.cpp` lines 143-156; per-sample loop
`train_epoch`, `src/main_xor.cpp` lines 35-55; mini-batch epoch loop `train`,
`src/main_mnist.cpp` lines 45-85; PRNG `nn_seed`/`nn_rand_u32`/`nn_uniform`,
`src/nn.cpp` lines 8-31.

## 8. Initialization: why the starting weights are scaled

Start all weights at 0 and every neuron in a layer computes the same thing
forever (symmetry never breaks). Start them too large and sigmoids saturate
(derivative ~0, learning stalls); too small and signals fade to nothing after
a few layers. The fix is to draw `W ~ uniform(-s, s)` with `s` chosen so the
*variance* of a layer's output roughly equals the variance of its input:

- **Xavier** (sigmoid/softmax layers): `s = sqrt(6 / (in + out))`
- **He** (ReLU layers): `s = sqrt(2 / in)` — ReLU zeroes about half its
  inputs, halving the variance, so the weights get twice the Xavier variance
  to compensate.

Biases start at 0 — with random weights, symmetry is already broken.

**-> code:** `layer_init`, `src/nn.cpp` lines 45-63 (the comment above it
carries this same argument).

## 9. The MNIST data: IDX format, downloads, CSV fallback

MNIST ships as four IDX files: train/test images and train/test labels.
An IDX header is big-endian 32-bit integers: a magic number (0x00000803 for
image files: 3 dimensions; 0x00000801 for label files: 1 dimension), then the
dimension sizes (60000 x 28 x 28 for training images). After the header come
raw bytes: pixels 0-255 (scaled to 0..1 by the loader), labels 0-9.

Download (~11 MB packed; yann.lecun.com is unreliable, use a mirror):

    curl -L -o data/train-images-idx3-ubyte.gz https://ossci-datasets.s3.amazonaws.com/mnist/train-images-idx3-ubyte.gz
    curl -L -o data/train-labels-idx1-ubyte.gz https://ossci-datasets.s3.amazonaws.com/mnist/train-labels-idx1-ubyte.gz
    curl -L -o data/t10k-images-idx3-ubyte.gz  https://ossci-datasets.s3.amazonaws.com/mnist/t10k-images-idx3-ubyte.gz
    curl -L -o data/t10k-labels-idx1-ubyte.gz  https://ossci-datasets.s3.amazonaws.com/mnist/t10k-labels-idx1-ubyte.gz
    gzip -d data/*.gz

Other mirrors: `https://storage.googleapis.com/cvdf-datasets/mnist/` (same
file names), or any of the many GitHub-hosted copies. If IDX links ever rot
completely, the loader also accepts a CSV file (pass a path ending in
`.csv`): one image per line, `label,p0,p1,...,p783` with pixels 0-255 — the
format used by the popular "mnist_train.csv" redistributions.

**-> code:** `read_be_u32` (big-endian header words), `src/data_mnist.cpp`
lines 23-34; `load_idx` lines 36-79; `load_csv` lines 81-112; every failure
prints these download instructions and returns cleanly (SRS NN-9) — `fail`,
lines 8-20.

## 10. Running everything (and the hand-check session)

Build (MSYS2 UCRT64 on Windows; every target also has its plain g++ line as a
comment in the Makefile):

    mingw32-make            # or: make; builds xor, gradcheck, mnist

    g++ -std=c++17 -Wall -Wextra -O2 -o xor src/main_xor.cpp src/nn.cpp src/activations.cpp src/loss.cpp

Run:

    ./gradcheck                       # proves backprop: GRADCHECK PASS
    ./xor                             # trains XOR, prints the truth table
    ./xor --seed 7                    # same but different reproducible run
    ./mnist                           # 10 epochs to ~97% test accuracy
    ./mnist --save w.bin              # train, then save the weights
    ./mnist --load w.bin --eval       # no training: accuracy from saved weights
    ./mnist --load w.bin --predict 7  # one test digit as ASCII art

**The hand-check session** (SRS acceptance 5.2 — the core learning exercise):

    ./xor --trace

prints ONE complete training step on the sample `x=(1,0), y=1` — every
initial weight, every `z_j` term by term, every `a_j`, the loss, every delta,
every gradient, and every updated weight. Take paper and a calculator, start
from the printed initial `W1/b1/W2/b2`, and reproduce each printed number
with the formulas of sections 3, 5 and 7:

1. forward: `z1_j = W1_j0*1 + W1_j1*0 + b1_j`, `a1_j = 1/(1+e^-z1_j)`,
   then `z2_0 = sum_j W2_0j*a1_j + b2_0`, `a2_0 = sigmoid(z2_0)`
2. loss: `L = (a2_0 - 1)^2`, `dL/da = 2*(a2_0 - 1)`
3. deltas: `delta2_0 = dL/da * a2_0*(1-a2_0)`,
   `delta1_j = W2_0j * delta2_0 * a1_j*(1-a1_j)`
4. gradients: `dW2_0j = delta2_0 * a1_j`, `dW1_j0 = delta1_j * 1`,
   `dW1_j1 = delta1_j * 0 = 0`, `db = delta`
5. update: `w_new = w_old - 0.5 * gradient`

If every number matches the printout, you have personally executed
backpropagation. That is the point of this project.

**-> code:** the trace printers, `src/main_xor.cpp` lines 69-172.
