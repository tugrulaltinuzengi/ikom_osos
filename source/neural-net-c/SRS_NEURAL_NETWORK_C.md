# Requirement Specification — SRS-02
# Neural Network from Scratch in C (Educational)

| | |
|---|---|
| **Project** | `neural_net_c` — a from-scratch MLP in plain C, written to be *read* |
| **Date** | 2026-07-13 |
| **Status** | Draft for approval |
| **Author** | Tuğrul + Claude |

> **Amendment (2026-07-14):** Implementation language changed from C99 to
> **C++17** (owner's decision, made after the core library + gradcheck were
> complete). Everything educational stays as specified: explicit loops, no
> matrix/autograd/BLAS libraries (standard-library containers such as
> `std::vector` are allowed), same size limits, same functional requirements.
> `malloc/free` requirements (NR-5) are satisfied via RAII: every vector is
> sized once at network construction and freed automatically at destruction.
> Files are `.hpp/.cpp`; builds use `g++ -std=c++17`; references below to
> `nn.c` etc. should be read as `nn.cpp`.

---

## 1. Introduction

### 1.1 Purpose
Produce a C program whose **primary output is understanding**: every fundamental
building block of a feed-forward neural network — neuron, weight, bias, layer,
activation function, forward pass, loss, gradient, backpropagation, training
loop — must be visible as a small, named, commented piece of C code that maps
1:1 onto the underlying math. Accuracy numbers are secondary; readability and
traceability are the product.

### 1.2 Scope — progressive, one codebase
- **Stage 1 — XOR.** A tiny MLP (2 inputs → 4 hidden → 1 output) learns XOR.
  Small enough that a single training step can be traced by hand on paper
  against the program's own printed trace.
- **Stage 2 — MNIST.** The **same library code**, no rewrites, scaled up
  (784 → 128 → 10) to classify handwritten digits from the real MNIST dataset.
  Proves the building blocks generalize.

**Out of scope:** GPU, threading, convolutions, autograd frameworks, any
external library beyond libc + `math.h`. PC only (Windows, gcc/MinGW); no
ESP32 port in this project.

### 1.3 The building blocks the code must expose (checklist)
Each item below must exist as its **own clearly named function or struct**,
with a comment stating the math it implements:

1. **Neuron / Layer** — `Layer` struct: weight matrix `W`, bias vector `b`,
   and the per-forward-pass caches `z` (pre-activation) and `a` (activation).
2. **Weighted sum** — `z = W·x + b` (explicit loops, no matrix library).
3. **Activation functions** — `sigmoid`, `relu`, `softmax`, each next to its
   derivative (`*_prime`).
4. **Forward pass** — `nn_forward()`: input → layer by layer → output.
5. **Loss** — MSE (Stage 1) and cross-entropy (Stage 2), each with the
   derivative used to start backprop.
6. **Backpropagation** — `nn_backward()`: the chain rule written out —
   output delta, hidden delta `δˡ = (Wˡ⁺¹ᵀ δˡ⁺¹) ⊙ σ'(zˡ)`, and the gradients
   `∂L/∂W = δ · aᵀ`, `∂L/∂b = δ`.
7. **Parameter update** — plain SGD `w ← w − η·∂L/∂w` (optionally mini-batch
   averaging in Stage 2).
8. **Training loop** — epochs, shuffling, periodic loss/accuracy reporting.
9. **Initialization** — seeded PRNG, small random weights (Xavier-style
   scaling, explained in a comment).

---

## 2. Deliverables & structure

```
neural_net_c/
├── SRS_NEURAL_NETWORK_C.md      (this file)
├── EXPLANATION.md               the "textbook": math → code walkthrough
├── Makefile                     gcc builds; also documents the plain commands
├── src/
│   ├── nn.h / nn.c              Layer + Network structs, forward, backward, update
│   ├── activations.h / .c       sigmoid/relu/softmax + derivatives
│   ├── loss.h / .c              mse/cross-entropy + derivatives
│   ├── data_mnist.h / .c        IDX file loader (magic 0x00000803/0x00000801)
│   ├── main_xor.c               Stage 1 entry point
│   ├── main_mnist.c             Stage 2 entry point
│   └── gradcheck.c              numerical-vs-analytical gradient verification
└── data/                        MNIST IDX files (download instructions in EXPLANATION.md)
```

---

## 3. Functional requirements
| ID | Requirement |
|---|---|
| NN-1 | Builds with `make` (and each target also with a single documented `gcc` line) under MinGW/gcc on Windows; C99; only libc + `-lm` |
| NN-2 | `xor` binary: trains 2-4-1 sigmoid MLP to MSE < 0.01, then prints the truth table (outputs ~0,1,1,0). Runtime < 1 s |
| NN-3 | `xor --trace`: prints **every** number of one full training step (each z, a, δ, gradient, updated weight) so it can be checked by hand — the core learning tool |
| NN-4 | `gradcheck` binary: compares analytical backprop gradients against centered finite differences `(L(w+ε)−L(w−ε))/2ε`; passes iff max relative error < 1e-4. This *proves* the backprop code is correct |
| NN-5 | `mnist` binary: loads the 4 IDX files, trains 784-128-10 (ReLU hidden, softmax output, cross-entropy, mini-batch SGD), reaches **≥ 95 %** test accuracy within ≤ 10 epochs / ≤ 5 min on the PC |
| NN-6 | Per-epoch reporting: epoch, training loss, test accuracy, elapsed seconds |
| NN-7 | `--seed N` makes runs bit-for-bit reproducible; default seed fixed |
| NN-8 | `mnist --save w.bin` / `--load w.bin --eval`: save/load weights, inference-only mode; `--predict <index>` prints one test image as ASCII art with the predicted vs true label |
| NN-9 | Missing/corrupt data files → clear error message with download instructions, no crash |

## 4. Non-functional (readability) requirements
| ID | Requirement |
|---|---|
| NR-1 | No function > ~40 lines; no file > ~300 lines |
| NR-2 | Variable names match the math notation used in EXPLANATION.md (`W`, `b`, `z`, `a`, `delta`, `eta`) |
| NR-3 | Every non-trivial loop has a comment saying which formula it computes |
| NR-4 | Explicit `for`-loops over neurons — no clever pointer tricks, no macro magic |
| NR-5 | Memory: allocated once at network creation, freed once at destruction; sizes visible in the struct |
| NR-6 | Console output ASCII-only (Turkish Windows cp1254 console) |
| NR-7 | EXPLANATION.md walks: perceptron → why hidden layers (XOR!) → chain rule → backprop derivation → mini-batches, each section ending with "this is function X in file Y, lines …" |

## 5. Acceptance criteria
1. `make && xor` prints a correct XOR truth table (NN-2).
2. A hand-calculation of one step from `xor --trace` matches the printout (NN-3) — done together as a learning session.
3. `gradcheck` passes (NN-4).
4. `mnist` reaches ≥ 95 % test accuracy, reproducibly with the default seed (NN-5, NN-7).
5. `mnist --load w.bin --predict 7` shows the digit as ASCII art with the right label (NN-8).
6. Reading EXPLANATION.md side-by-side with the code, every §1.3 building block can be pointed at within 10 seconds.

## 6. Risks
| Risk | Mitigation |
|---|---|
| MNIST download links rot (yann.lecun.com is flaky) | EXPLANATION.md lists mirrors (e.g. GitHub-hosted copies); loader also accepts a documented CSV fallback |
| 95 % target vs simplicity tension | 784-128-10 + ReLU + minibatch SGD reliably hits ~97 %; no tricks needed |
| Educational trace floods the console on MNIST | `--trace` is XOR-only by design |
