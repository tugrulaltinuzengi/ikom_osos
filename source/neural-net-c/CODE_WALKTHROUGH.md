# CODE WALKTHROUGH — every file, every construct, in detail

`EXPLANATION.md` explains the **math** and points at the code.
This document explains the **code itself**: what every C++ keyword, every
standard-library call, and every non-obvious line in this project actually
does, file by file. Read Part I once (it covers each language feature a
single time), then read Part II next to the source files.

---

# PART I — The language and library toolbox this project uses

Nothing in this part is project-specific; it is the minimal C++ you need to
read every line of the source. Each item says *what it is*, *how it works
underneath*, and *where this project uses it*.

## I.1 The preprocessor: lines that start with `#`

Before the compiler proper ever runs, a text-rewriting pass (the
*preprocessor*) processes every line starting with `#`.

**`#include <vector>` / `#include "nn.hpp"`** — literally pastes the named
file's whole text into this spot. Angle brackets `<...>` search the
compiler's system directories (standard library headers); quotes `"..."`
search the project directory first. That is the entire mechanism by which
one file learns about functions defined in another: it pastes in their
*declarations*.

**Include guards** — every `.hpp` in this project starts and ends with:

```cpp
#ifndef NN_HPP     // "if the macro NN_HPP is not defined yet..."
#define NN_HPP     // "...define it now..."
...                // ...the actual header content...
#endif             // end of the #ifndef block
```

Because headers include other headers, the same file can get pasted twice
into one translation unit. Defining a struct twice is a compile error. The
guard makes the second paste expand to nothing: the first paste defined
`NN_HPP`, so the second paste's `#ifndef` is false and everything to
`#endif` is skipped.

**Header (`.hpp`) vs source (`.cpp`)** — the header holds *declarations*
(function signatures, struct layouts): enough for other files to call the
functions and use the types. The `.cpp` holds the *definitions* (the actual
bodies). Each `.cpp` is compiled independently into an object file; the
**linker** then stitches the object files into one `.exe`, matching each
call to the one definition with the same name and signature.

## I.2 Fundamental types

| type | what it is | in this project |
|---|---|---|
| `double` | 64-bit IEEE-754 floating point, ~15-16 significant digits | every weight, activation, gradient. Chosen over 32-bit `float` so gradcheck's tiny differences (~1e-9) are measurable |
| `int` | 32-bit signed integer | loop counters, sizes, labels |
| `unsigned int` | 32-bit integer, no sign, wraps modulo 2^32 | the PRNG state — we *want* modulo-2^32 wraparound, and bit shifts on signed ints are legally murky |
| `size_t` | unsigned type big enough for any object size (64-bit here) | indexing big arrays: `60000 * 784` overflows nothing as `size_t` |
| `bool` | `true` / `false` | success flags |
| `char` / `unsigned char` | one byte | raw file bytes, pixel bytes 0..255, C strings |

**Implicit conversions and casts.** C++ silently converts `int -> double`
(safe) and `double -> int` (truncates!). Where a conversion is intentional
this code spells it out with `static_cast<T>(expr)`, e.g.
`static_cast<size_t>(out) * in` — do the multiplication *in* the wide type
so it cannot overflow, or `static_cast<int>(x[...] * 9.99)` — deliberate
truncation to pick an ASCII-ramp index. `static_cast` is just C's `(T)expr`
cast with compile-time checking and greppable syntax.

## I.3 `struct`: a bundle of named fields

```cpp
struct Layer {
    int in = 0, out = 0;
    std::vector<double> W;
    ...
    Activation act = Activation::Sigmoid;
};
```

A `struct` defines a new type whose objects contain all the listed fields
laid out together. `Layer ly;` creates one; `ly.out` reads a field. The
`= 0` / `= Activation::Sigmoid` are **default member initializers**: any
`Layer` constructed without explicit values starts with these (and vectors
default-construct to empty), so a fresh `Layer` is never garbage.

In C++ (unlike C) a struct can also contain **member functions** — see
`Network` below. `struct` and `class` are the same feature; `struct` just
defaults to public visibility, which suits this project: the whole point is
that you can look inside.

## I.4 `enum class`: a type-safe set of named constants

```cpp
enum class Activation { Sigmoid, Relu, Softmax };
```

Defines a new type with exactly three possible values, written
`Activation::Relu` etc. Compared to C's plain `enum`: the names live inside
the enum (no collisions), and there is **no implicit conversion to int** —
you cannot accidentally do arithmetic on one. When we genuinely need the
number (writing weights to a binary file), we convert explicitly:
`static_cast<int>(ly.act)` — Sigmoid is 0, Relu 1, Softmax 2, in declaration
order.

## I.5 References: `&` in a parameter or variable

```cpp
void softmax(const std::vector<double> &z, std::vector<double> &a);
Layer &ly = layers[l];
```

A reference is **another name for an existing object** — no copy is made.
Under the hood the compiler passes the object's address, like a pointer, but
you use it with plain `.` syntax and it can never be null or reseated.

Three flavors used here:

- `const std::vector<double> &z` — read-only alias. The function can look
  at `z` but any attempt to modify it is a compile error. This is the
  default way to pass anything big: copying a 784-element vector on every
  call would be pure waste.
- `std::vector<double> &a` — writable alias: the function's *output
  parameter*. `softmax(ly.z, ly.a)` fills the layer's own `a` in place.
- `Layer &ly = layers[l];` — a local shorthand so the hot loops can say
  `ly.W[...]` instead of `layers[l].W[...]`. Zero cost; purely readability.

**Returning a reference.** `Network::forward` returns
`const std::vector<double>&` — a reference to the *last layer's internal
`a` vector*. No copy, but two rules follow: the reference is valid only
while the network object exists, and the **next** `forward()` call
overwrites the same storage. Every caller in this project reads it before
calling forward again, so this is safe here — but it is the one sharp edge
of the design, so know it.

## I.6 `std::vector<double>` — the workhorse container

A `std::vector<T>` is a resizable array. Internally it is exactly three
things: a pointer to a heap-allocated contiguous block of `T`, the current
element count (`size()`), and the block's capacity. Because storage is
contiguous, `v[i]` compiles to the same single memory access as a C array —
there is no performance penalty in the hot loops.

Operations used in this project:

- `v.resize(n)` — make size n. New `double` elements are **value-initialized
  to 0.0** (that's why `W.resize(...)` needs no separate zeroing before
  being overwritten with random values).
- `v.assign(n, 0.0)` — set size to n and every element to 0.0. Used in
  `layer_init` for `b`, `z`, `a`, `delta`, `dW`, `db`.
- `v[i]` — element access, **no bounds checking** (like a C array; fast).
- `v.size()` — element count, returns `size_t` (hence the
  `static_cast<int>` sprinkles when we want an `int` loop bound).
- `v.data()` — raw `double*` to the first element; how we hand the block to
  C functions like `memcpy` and `fread`/`fwrite`.
- `v.push_back(x)` — append one element, growing the block if needed
  (amortized O(1): when full, it allocates a bigger block — typically 2x —
  and moves everything). Used only in the CSV loader where the row count
  is unknown in advance.
- `std::vector<double> dW_saved = ly.dW;` — **copying a vector copies all
  its elements** (a deep copy). gradcheck uses this to snapshot the
  analytical gradients before the numerical pass overwrites the network.
- `{1.0, 2.0, 3.0}` — brace initialization builds a vector from listed
  elements; `std::vector<double> a(3)` builds 3 zeros; `y(N_OUT, 0.0)`
  builds N_OUT copies of 0.0.

**RAII — why there is no `free()` anywhere.** A vector's destructor releases
its heap block automatically when the vector goes out of scope, and a
`Network`'s destructor destroys its `layers` vector which destroys each
`Layer` which destroys each of its 7 vectors. Allocation happens exactly
once (in `layer_init`), deallocation exactly once (automatically) — the C
version's `malloc`/`calloc`/`free` bookkeeping, NR-5, enforced by the
language instead of by discipline. This idiom is called RAII: *Resource
Acquisition Is Initialization*.

`std::vector<std::vector<double>>` (in `trace_update`) is simply a vector
whose elements are themselves vectors — used as "one saved copy per layer".

## I.7 Functions: `static`, members, constructors, `::`

**`static` at file scope** (on a function or global variable) means
*internal linkage*: the name is invisible outside this `.cpp` file. All the
helpers — `layer_init`, `fail`, `read_be_u32`, `trace_*`, `evaluate` … —
are `static`: they are private implementation details, and two files could
each have their own `static void helper()` without colliding at link time.
(The PRNG state `static unsigned int rng_state = 1;` is the same idea for a
variable: one hidden global, initialized once, invisible outside `nn.cpp`.)

**Member functions.** Declared inside the struct
(`const std::vector<double> &forward(const std::vector<double> &x);`),
defined in the `.cpp` with the **scope-resolution operator** `::`:

```cpp
const std::vector<double> &Network::forward(const std::vector<double> &x) { ... }
```

`Network::` says "this `forward` is the one belonging to `Network`". Inside
a member function, field names like `layers` implicitly mean "this object's
`layers`". Call syntax: `net.forward(x)`.

**Constructor.** A member function with the struct's own name and no return
type, run automatically when the object is created:

```cpp
Network net({2, 4, 1}, {Activation::Sigmoid, Activation::Sigmoid}, seed);
```

The braces build the two vectors in place (an `initializer_list`
conversion); the constructor body then seeds the PRNG, validates, and sizes
every layer. There is no separate "init" function to forget to call — an
existing `Network` is always a valid one.

**Function pointers.** gradcheck needs "which loss?" as a *value*:

```cpp
typedef double (*LossFn)(const std::vector<double> &a, const std::vector<double> &y);
```

reads inside-out as: `LossFn` is a pointer to a function taking two vector
references and returning `double`. Since `mse` and `cross_entropy` have
exactly that signature, plain `mse` (no parentheses) is a valid `LossFn`
value, and `loss_fn(a, y)` calls whatever it points to. This is how ONE
`gradcheck_config` routine checks both loss setups.

**Range-based for.** `for (const Layer &ly : net.layers) { ... }` visits
every element of the vector in order; the `&` again means "alias, don't
copy each Layer".

## I.8 Operators that deserve a second look

- **Ternary** `cond ? a : b` — an *expression* that yields `a` if cond is
  true else `b`. `z > 0.0 ? z : 0.0` *is* ReLU.
- **Compound assignment** `+=`, `-=`, `/=` — `a += b` is `a = a + b`.
  Gradient *accumulation* is literally the `+=` in `backward`.
- **Bitwise XOR** `^` and **shifts** `<<`, `>>` — on `unsigned int`,
  `x << 13` moves every bit 13 places left (top bits fall off, zeros come
  in); `x ^= x << 13` XORs the shifted copy back in. Three such lines are
  the entire xorshift32 generator (see II.4).
- **Modulo** `%` — remainder. `nn_rand_u32() % (i + 1)` maps a random
  32-bit number into `0..i` for the shuffle. (Pedantic footnote: because
  2^32 is not divisible by `i+1`, low values are very slightly more likely —
  "modulo bias". At i <= 59999 the bias is ~1e-5 relative and utterly
  irrelevant here; production RNG libraries do rejection sampling instead.)
- **Pre/post increment** `++i` / `i++` — add one; as a statement they are
  equivalent. `argv[++i]` uses the *pre* form's value: advance first,
  then read — which is exactly "consume the flag's argument".
- `(void) z;` — evaluates a parameter and throws the result away; the
  idiomatic way to tell the compiler "yes, this parameter is deliberately
  unused" so `-Wextra` stays quiet (`delta_softmax_ce` doesn't need `z`).

## I.9 The C standard library, header by header

C++ inherits C's library; `<cmath>` etc. are C's headers with the functions
placed in namespace `std`. This project deliberately uses these simple,
transparent functions instead of C++ streams — closer to the metal, easier
to map to what actually happens.

### `<cmath>` — math on doubles
- `std::exp(x)` = e^x, `std::log(x)` = natural log (x<=0 is an error —
  hence the clamp in `cross_entropy`), `std::sqrt(x)`.
- `std::fabs(x)` — absolute value; `std::fmax(a,b)` — the larger value.
  Used in gradcheck's relative-error formula.

### `<cstdio>` — formatted output and binary file I/O
- `std::printf(format, ...)` writes to the console; `std::fprintf(stderr,
  ...)` writes to the *error* stream (so error text is separable from
  program output); `std::putchar(c)` writes one character.
- The **format string mini-language** — every `%...` consumes one argument:
  - `%d` int; `%5d` int right-padded to width 5; `%2d` width 2.
  - `%f` double; `%.6f` six digits after the decimal point; `%+.6f` same
    but always with a sign (the trace uses this so columns align);
    `%.1e` scientific notation with 1 decimal (gradcheck's `1.9e-10`);
    `%.2f%%` — `%%` is a literal percent sign.
  - `%s` C string, `%c` one char, `\n` newline, `\t` tab.
- Files: `std::fopen(path, "rb")` opens for **r**eading in **b**inary mode
  (no newline translation — vital on Windows, where text mode rewrites
  `\n` <-> `\r\n` and would corrupt pixel data). `"wb"` = write binary.
  Returns a `FILE*` stream handle, or NULL on failure — **always checked**
  in this project. `std::fclose(f)` releases it.
- `std::fgetc(f)` reads ONE byte, returning it as an `int`. Why int and not
  char? Because it must be able to return the special value `EOF` (-1,
  end-of-file/error) *distinguishably* from the valid byte 255.
- `std::fread(ptr, size, count, f)` reads up to `count` items of `size`
  bytes each into memory at `ptr`, returning how many *complete items* it
  actually read — compare with the expected count to detect truncated
  files. `std::fwrite` is the mirror image.
- `std::fgets(buf, n, f)` reads one text line (up to n-1 chars, keeps the
  `\n`, adds `\0`), returns NULL at end of file — the CSV reader's loop
  condition.

### `<cstring>` — raw memory and C-string helpers
- `std::strcmp(a, b)` compares two C strings, returning 0 when **equal**
  (hence the `== 0` in all the argv tests).
- `std::strlen(s)` — length up to the terminating `\0`.
- `std::memcpy(dst, src, nbytes)` — copy raw bytes, the fastest way to move
  a 784-double row out of the big image block: note the byte count is
  `N_IN * sizeof(double)`, not `N_IN`.
- `std::memcmp(a, b, n)` — compare n raw bytes; 0 means identical (used to
  check the `"NNC1"` magic).

### `<cstdlib>` — conversions and process control
- `std::strtol(p, &end, 10)` parses a base-10 integer starting at `p`,
  **and writes the position where parsing stopped into `end`**. The CSV
  loader exploits this: passing `&p` makes the pointer crawl across the
  line, number by number, with the `,` check in between. `std::strtoul` is
  the unsigned variant (used for `--seed`); `std::atoi` is the quick-and-dirty
  version without error reporting (fine for `--predict 7`).
- `std::exit(1)` ends the process immediately with exit code 1 (convention:
  0 = success, nonzero = failure — this is what `$LASTEXITCODE` /  `$?`
  see, and what `gradcheck` uses to make CI-style scripting possible).

### `<ctime>` — timing
- `std::clock()` returns processor ticks since program start;
  `CLOCKS_PER_SEC` converts to seconds. On this platform (MinGW/Windows)
  it behaves like wall-clock time of the process; precision is
  milliseconds — plenty for "elapsed 11.0s" epoch reporting.

### `<cassert>`
- `assert(expr)` — if expr is false, print file:line and abort. Used in
  gradcheck's sanity checks. Compiled OUT entirely if `NDEBUG` is defined,
  which is why asserts guard *tests*, never *user input*.

### `main`, `argc`, `argv`
`int main(int argc, char **argv)` — the OS calls this. `argv` is an array
of C strings: `argv[0]` is the program name, `argv[1]..argv[argc-1]` are
the command-line words. The parsers here walk `i` from 1 to argc-1,
`strcmp`-ing each word; flags that take a value do `argv[++i]` to consume
the next word (guarded by `i + 1 < argc` so `--seed` with nothing after it
can't read past the array).

## I.10 The Makefile, line by line

`make` is a dependency engine: "if any prerequisite is newer than the
target, run the recipe".

```make
CXX      = g++                          # variable: which compiler
CXXFLAGS = -std=c++17 -Wall -Wextra -O2 # variable: flags for every compile
```

- `-std=c++17` — the language edition to compile as.
- `-Wall -Wextra` — enable (almost) all warnings; this project treats any
  warning as a bug to fix.
- `-O2` — optimize. The explicit triple loops rely on this: at -O2 the
  compiler vectorizes/unrolls them into code within ~2-4x of a tuned BLAS
  for these sizes, with zero library magic.

```make
xor: src/main_xor.cpp $(LIB_SRC)
	$(CXX) $(CXXFLAGS) -o $@ $^
```

Reads: target `xor` depends on those sources; if any changed, run the
recipe. `$@` expands to the target name (`xor`), `$^` to *all*
prerequisites (all the .cpp files). Recipe lines MUST start with a real TAB
character — make's most famous trap. `-o xor` names the output; on Windows
g++ produces `xor.exe`.

`all: xor gradcheck mnist` is the default target (first in the file);
`.PHONY: all clean` tells make these are command names, not files, so a
stray file named `clean` could never satisfy-and-skip them. The `clean`
recipe has both a `del` (cmd.exe) and an `rm` (sh) line, each prefixed with
`-` = "ignore this line's failure", so it works from both shell families.

---

# PART II — File by file

## II.1 `src/activations.hpp` / `activations.cpp`

**Purpose:** the three nonlinearities and their derivatives; free functions
with no state — pure math.

```cpp
double sigmoid(double z) {
    return 1.0 / (1.0 + std::exp(-z));
}
```
Literal transcription of s(z) = 1/(1+e^-z). Note `1.0` not `1`: keeps every
operand a double (an `int` would be converted anyway, but the code says
what it means).

```cpp
double sigmoid_prime(double z) {
    double s = sigmoid(z);
    return s * (1.0 - s);
}
```
Computes sigmoid **once** into a local, then uses it twice — cheaper and
clearer than calling `sigmoid(z)` twice.

```cpp
double relu(double z)       { return z > 0.0 ? z : 0.0; }
double relu_prime(double z) { return z > 0.0 ? 1.0 : 0.0; }
```
The ternary *is* the piecewise definition. Mathematical footnote: at exactly
z = 0 ReLU has no derivative; returning 0 there is the universal convention
(and z lands on exactly 0.0 with probability ~0 anyway).

```cpp
void softmax(const std::vector<double> &z, std::vector<double> &a) {
    int n = static_cast<int>(z.size());
    double m = z[0];
    for (int j = 1; j < n; j++)   /* m = max_k z_k */
        if (z[j] > m) m = z[j];
```
First pass: find the maximum. Start from `z[0]`, scan the rest. (This is why
softmax takes whole vectors: it needs *all* entries before producing *any*
output — a genuinely vector-valued activation, unlike sigmoid/relu.)

```cpp
    double sum = 0.0;
    for (int j = 0; j < n; j++) {
        a[j] = std::exp(z[j] - m);
        sum += a[j];
    }
    for (int j = 0; j < n; j++)
        a[j] /= sum;
```
Second pass: exponentiate **with m subtracted** and accumulate the sum;
third pass: normalize. Subtracting the max is invisible algebraically
(numerator and denominator both gain a factor e^-m which cancels) but keeps
`exp` in a safe range: `exp(1000)` would overflow `double` to infinity and
poison everything downstream with NaNs; `exp(z - max)` is at most
`exp(0) = 1`.

Output parameter `a` is written in place — caller (the forward pass) passes
the layer's own `a` cache, so no allocation happens per call.

## II.2 `src/loss.hpp` / `loss.cpp`

**Purpose:** the two loss functions, each with the derivative that starts
backprop.

```cpp
double mse(const std::vector<double> &a, const std::vector<double> &y) {
    int n = static_cast<int>(a.size());
    double sum = 0.0;
    for (int j = 0; j < n; j++) {
        double diff = a[j] - y[j];
        sum += diff * diff;
    }
    return sum / n;
}
```
`diff * diff` instead of `pow(diff, 2)`: a multiplication is one
instruction; `pow` is a general-purpose library call. Dividing by `n` at the
end (not inside the loop) does one division instead of n.

```cpp
double mse_prime(double a_j, double y_j, int n) {
    return 2.0 * (a_j - y_j) / n;
}
```
Note the signature: *scalar*. The derivative of MSE w.r.t. ONE output
`a_j` — callers apply it element-wise, keeping the chain rule visible at the
call site (`main_xor.cpp`'s `output_delta`).

```cpp
double cross_entropy(const std::vector<double> &a, const std::vector<double> &y) {
    ...
        double a_j = a[j];
        if (a_j < 1e-12)          /* clamp to avoid log(0) = -inf */
            a_j = 1e-12;
        sum += y[j] * std::log(a_j);
    ...
    return -sum;
}
```
The clamp: if the network ever outputs a probability of exactly 0 for the
true class, log gives -infinity and the whole training loss becomes
meaningless (inf/NaN propagates through every later computation). Clamping
at 1e-12 caps the per-sample loss at ~27.6 instead. The local copy `a_j`
means we clamp our *reading* of the value, never modify the caller's data —
`a` is `const&`, the compiler would refuse anyway.

```cpp
void softmax_ce_delta(const std::vector<double> &a, const std::vector<double> &y,
                      std::vector<double> &delta) {
    for (int j = 0; j < n; j++)
        delta[j] = a[j] - y[j];
}
```
The celebrated cancellation (EXPLANATION.md §5.2) reduced to one subtraction
per class. This function exists (rather than inlining `a - y` at call sites)
so the *name* documents where the formula comes from.

## II.3 `src/nn.hpp` — the data model

Read the `Layer` struct as a table of "what memory a layer owns" (sizes in
the comments are the NR-5 requirement made visible):

```cpp
struct Layer {
    int in = 0, out = 0;
    std::vector<double> W;      /* out*in  weights   */
    std::vector<double> b;      /* out     biases    */
    std::vector<double> z, a, delta;   /* out each — caches */
    std::vector<double> dW, db;        /* gradient accumulators */
    Activation act = Activation::Sigmoid;
};
```

**Why is W one flat vector and not `vector<vector<double>>`?** Row-major
flattening: row j (all weights into neuron j) occupies the contiguous slice
`W[j*in] .. W[j*in + in - 1]`, so `W[j*in + i]` is "weight from input i to
neuron j". One flat block = one allocation, perfect cache locality in the
hot loops, and the indexing formula itself teaches you how matrices live in
memory. A vector-of-vectors would scatter rows across the heap.

`Network` owns `std::vector<Layer> layers` and three member functions —
`forward`, `backward`, `update` — plus the constructor. That is the entire
API surface of the library.

The PRNG trio (`nn_seed`, `nn_rand_u32`, `nn_uniform`) are free functions,
declared here because both the library (weight init) and the programs
(shuffles, gradcheck inputs) need them.

## II.4 `src/nn.cpp` — PRNG, construction, forward, backward, update

### The PRNG

```cpp
static unsigned int rng_state = 1;

void nn_seed(unsigned int s) {
    rng_state = (s == 0) ? 0x9e3779b9u : s;
}
```
One file-private (`static`) global holds the generator state. Seed 0 is
remapped because of the fixed-point problem explained below; `0x9e3779b9`
(the golden-ratio constant, a traditional "well-mixed bits" value) is
arbitrary but fixed, so `--seed 0` is still reproducible. The `u` suffix
makes the literal unsigned.

```cpp
unsigned int nn_rand_u32() {
    unsigned int x = rng_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    rng_state = x;
    return x;
}
```
Marsaglia's xorshift32. Each line XORs the state with a shifted copy of
itself; the three shifts (13, 17, 5 — one of the few magic triples that
work) scramble bits enough that the sequence passes basic randomness tests
and has period 2^32 - 1: it visits *every* nonzero 32-bit value exactly once
before repeating. Zero is excluded because shifting 0 gives 0 and XOR with 0
changes nothing — a state of 0 stays 0 forever, which is why `nn_seed`
refuses it.

Why not `rand()` or `std::mt19937`? `rand()`'s algorithm differs per C
library, and even `mt19937` (whose raw stream IS standardized) is normally
used through `std::uniform_real_distribution`, whose mapping the standard
does *not* pin down. Owning all 8 lines of the generator is the only way
`--seed 42` gives bit-identical training runs on any compiler (NN-7) — and
it demystifies "random": it's just bit-mixing.

```cpp
double nn_uniform(double lo, double hi) {
    double u = nn_rand_u32() / 4294967296.0; /* u32 / 2^32, so u in [0,1) */
    return lo + u * (hi - lo);
}
```
Divide by 2^32 (the constant is 4294967296.0; the `.0` forces float
division, not integer division!) to map 0..2^32-1 into [0,1), then stretch
to [lo,hi).

### `layer_init` and the constructor

```cpp
static void layer_init(Layer &ly, int in, int out, Activation act) {
    ...
    ly.W.resize(static_cast<size_t>(out) * in);
    ly.b.assign(out, 0.0);
    ... (z, a, delta, dW, db likewise)
    double s = (act == Activation::Relu) ? std::sqrt(2.0 / in)
                                         : std::sqrt(6.0 / (in + out));
    for (int j = 0; j < out; j++)
        for (int i = 0; i < in; i++)
            ly.W[j * in + i] = nn_uniform(-s, s);
}
```
All seven allocations happen here and only here. The scale `s` implements
He (ReLU) or Xavier (others) initialization — the *why* is a long comment
in the source and EXPLANATION.md §8. `2.0 / in` — again the `.0` guarantees
float division (`2 / in` would be integer division = 0 for in > 2!).

```cpp
Network::Network(const std::vector<int> &sizes, const std::vector<Activation> &acts,
                 unsigned int seed) {
    nn_seed(seed);
    for (int l = 0; l < n_layers - 1; l++)
        if (acts[l] == Activation::Softmax) { fprintf(stderr, ...); exit(1); }
    layers.resize(n_layers);
    for (int l = 0; l < n_layers; l++)
        layer_init(layers[l], sizes[l], sizes[l + 1], acts[l]);
}
```
Seeds first (so construction itself is reproducible), rejects softmax on a
hidden layer (backward's hidden-delta formula assumes elementwise
activations; failing loudly at construction beats silently training
garbage), then sizes each layer as a `sizes[l] -> sizes[l+1]` transition —
which is why `sizes` has one more entry than `acts`.

### `forward`

```cpp
const std::vector<double> &Network::forward(const std::vector<double> &x) {
    const std::vector<double> *in = &x;
    for (size_t l = 0; l < layers.size(); l++) {
        Layer &ly = layers[l];
        for (int j = 0; j < ly.out; j++) {
            double z = ly.b[j];
            for (int i = 0; i < ly.in; i++)
                z += ly.W[j * ly.in + i] * (*in)[i];
            ly.z[j] = z;
        }
        if (ly.act == Activation::Softmax) softmax(ly.z, ly.a);
        else
            for (int j = 0; j < ly.out; j++)
                ly.a[j] = (ly.act == Activation::Relu) ? relu(ly.z[j]) : sigmoid(ly.z[j]);
        in = &ly.a;
    }
    return *in;
}
```
The one genuinely pointer-y construct in the project: `in` is a **pointer to
a vector** (`const std::vector<double>*`). Why not a reference? Because
references cannot be re-seated, and this variable must *change what it
refers to* each iteration: first the caller's `x`, then layer 0's `a`, then
layer 1's `a`... `&x` takes an address; `(*in)[i]` dereferences the pointer
back into a vector and indexes it; `in = &ly.a` re-aims it.

The inner accumulation starts from `ly.b[j]` — the "+ b_j" of the formula
absorbed into the loop's starting value instead of a separate addition.

`ly.z[j] = z;` — the caches being *written during* forward is the collusion
between forward and backward: backward will read these exact values.

### `backward`

```cpp
void Network::backward(const std::vector<double> &x, const std::vector<double> &delta_out) {
    int L = static_cast<int>(layers.size());
    for (int j = 0; j < layers[L-1].out; j++)
        layers[L-1].delta[j] = delta_out[j];
```
Step 1: copy the caller-supplied output delta into the last layer's cache.
The *caller* computes it because it depends on the loss (design decision:
the library knows activations, not losses).

```cpp
    for (int l = L - 2; l >= 0; l--) {
        Layer &cur = layers[l], &nxt = layers[l+1];
        for (int j = 0; j < cur.out; j++) {
            double sum = 0.0;
            for (int k = 0; k < nxt.out; k++)
                sum += nxt.W[k * nxt.in + j] * nxt.delta[k];
            cur.delta[j] = sum * ((cur.act == Activation::Relu)
                                  ? relu_prime(cur.z[j]) : sigmoid_prime(cur.z[j]));
        }
    }
```
Step 2 walks **backwards** (`l--` from the second-to-last layer to 0 —
that's the "back" in backprop). Look hard at `nxt.W[k * nxt.in + j]`: with
row-major W, this reads *column j* of the next layer's matrix — i.e. the
**transpose** access Wᵀ, without ever materializing a transposed matrix.
Row k, column j = "the weight from OUR neuron j to THEIR neuron k", which is
precisely the path along which neuron j's error flows forward, so it is the
path along which blame flows back. Multiply by the local slope f'(z) and
the hidden delta is done.

```cpp
    for (int l = 0; l < L; l++) {
        Layer &ly = layers[l];
        const std::vector<double> &a_prev = (l == 0) ? x : layers[l-1].a;
        for (int j = 0; j < ly.out; j++) {
            for (int i = 0; i < ly.in; i++)
                ly.dW[j * ly.in + i] += ly.delta[j] * a_prev[i];
            ly.db[j] += ly.delta[j];
        }
    }
```
Step 3: gradients. `a_prev` is "what this layer saw as input": the raw `x`
for layer 0, otherwise the previous layer's cached activations — selected
by one ternary binding a reference. The `+=` (never `=`) is what makes
mini-batches work: call backward 64 times and dW holds the *sum* of 64
gradients; `update` divides by 64. Nothing about batching appears in
backward at all — the accumulate-then-average split keeps each function
single-purpose.

### `update`

```cpp
void Network::update(double eta, int batch_size) {
    ...
            ly.W[j * ly.in + i] -= eta * ly.dW[j * ly.in + i] / batch_size;
            ly.dW[j * ly.in + i] = 0.0;
    ...
}
```
`w -= eta * gradient / batch` — descent step and averaging fused into one
line — then immediately re-zero the accumulator so the next batch starts
clean. Update-and-clear being one operation means there is no separate
`zero_grad()` call to forget (a classic PyTorch beginner bug, designed out).

## II.5 `src/gradcheck.cpp` — the proof

Structure: sanity asserts, then the same check run over two configurations
via function pointers.

```cpp
static void sanity_checks() {
    assert(sigmoid(0.0) == 0.5);
    assert(relu(-3.0) == 0.0 && relu(2.0) == 2.0);
    ...
    assert(std::fabs((a[0] + a[1] + a[2]) - 1.0) < 1e-12);
```
Note which comparisons are exact (`== 0.5` — sigmoid(0) is exactly
1/(1+1), representable) and which are toleranced (softmax's sum suffers
rounding across exp/divide, so "within 1e-12"). Knowing *when* you may
compare floats exactly is itself a lesson.

```cpp
static double check_param_array(std::vector<double> &p, const std::vector<double> &g_ana,
                                Network &net, ...) {
    for (size_t k = 0; k < p.size(); k++) {
        double save = p[k];
        p[k] = save + EPS;
        double Lp = loss_fn(net.forward(x), y);
        p[k] = save - EPS;
        double Lm = loss_fn(net.forward(x), y);
        p[k] = save;
        double g_num = (Lp - Lm) / (2.0 * EPS);
        double rel = std::fabs(g_ana[k] - g_num)
                   / std::fmax(1e-8, std::fabs(g_ana[k]) + std::fabs(g_num));
        ...
```
The nudge-measure-restore pattern: because `p` is a *writable reference to
the network's real weight vector*, changing `p[k]` changes the network;
`net.forward(x)` then re-measures the loss with that one weight nudged; the
third assignment puts the world back exactly as found. Every parameter gets
two full forward passes — O(params × network-cost), brutally slow at MNIST
scale, which is why gradcheck runs on tiny 2-3-2 / 4-6-3 nets: correctness
transfers, cost doesn't.

The `rel` formula normalizes by the gradients' own magnitude (so "wrong by
1e-6" means something whether the gradient is 10 or 0.0001), with an
`fmax(1e-8, ...)` floor so a pair of genuinely-zero gradients cannot divide
by zero.

In `gradcheck_config`, note the order: ONE analytical forward+backward,
**copy dW/db aside** (`std::vector<double> dW_saved = ly.dW;` — deep copy,
I.6), and only then start nudging — the numerical passes run more forwards
which do not touch dW, but copying first also guards against any future
refactor that might.

`main` builds each config with fixed seeds, generates input/target from a
*separately* seeded stream (`nn_seed(123)` after construction — so tweaking
the net shape wouldn't silently change the test data), and turns the verdict
into an exit code: `return fail ? 1 : 0` via the if/printf at the end.

## II.6 `src/data_mnist.hpp` / `data_mnist.cpp` — bytes on disk to doubles in RAM

```cpp
static bool fail(const char *path, const char *what) {
    std::fprintf(stderr, "error: %s '%s'\n" "The MNIST data files belong..." ..., what, path);
    return false;
}
```
One funnel for every error (SRS NN-9). Two syntax notes: adjacent string
literals (`"..." "..."`) are glued into one at compile time — that's how a
long message spans lines — and returning `bool` lets callers write the
one-liner `return fail(path, "cannot open");`.

```cpp
static bool read_be_u32(std::FILE *f, unsigned int &v) {
    v = 0;
    for (int i = 0; i < 4; i++) {
        int c = std::fgetc(f);
        if (c == EOF) return false;
        v = (v << 8) | static_cast<unsigned int>(c);
    }
    return true;
}
```
IDX headers are **big-endian**: most significant byte first. Your x86 CPU is
little-endian, so you cannot just `fread` into an `unsigned int`. This
builds the value byte by byte: shift what we have 8 bits left, OR the new
byte into the bottom. After 4 bytes, `v` is correct *regardless of the
host's endianness* — portable by construction rather than by `#ifdef`.
(`fgetc` returning `int` so EOF is distinguishable: see I.9.)

`load_idx` then reads and validates the whole header with one boolean
chain:

```cpp
    bool header_ok =
        read_be_u32(fi, magic_i) && read_be_u32(fi, n_i) && ...
        magic_i == 0x00000803u && magic_l == 0x00000801u &&
        n_i == n_l && rows == 28 && cols == 28;
```
`&&` **short-circuits**: evaluation stops at the first false, so if a read
fails, the later comparisons (on now-meaningless variables) never execute.
The magics: 0x00000803 = "unsigned bytes, 3 dimensions" (images), 0x00000801
= 1 dimension (labels). Cross-checking `n_i == n_l` catches a mismatched
pair of files.

```cpp
    std::vector<unsigned char> raw(n_pix);
    ...
    std::fread(raw.data(), 1, n_pix, fi) == n_pix && ...
    for (size_t k = 0; k < n_pix; k++)
        out.images[k] = raw[k] / 255.0;
```
Bulk-read all 47MB of pixels in ONE `fread` into a byte buffer (item size 1,
count n_pix; the return-value comparison catches truncation), then convert
to doubles scaled into 0..1 — `raw[k] / 255.0`, the `.0` again forcing float
division. Why scale? Inputs in 0..1 match the weight-init math's variance
assumptions (§8); feeding 0..255 would blow the initial `z` values into
sigmoid-saturation land.

`load_csv` — the fallback path — shows the `strtol` pointer-walk (I.9):
`std::strtol(p + 1, &p, 10)` parses the number after the comma AND leaves
`p` at the first unparsed character, so the loop's `if (*p != ',')` check
is simultaneously the format validator and the walk. Rows are `push_back`ed
because a CSV's row count isn't known until end-of-file.

`mnist_load` is a 5-line dispatcher: `strcmp(img_path + len - 4, ".csv")`
compares the last four characters of the path (pointer arithmetic on the C
string) and routes to the right parser.

## II.7 `src/main_xor.cpp` — Stage 1 program

**Constants at the top** (`ETA`, `MAX_EPOCHS`, `TARGET_MSE`, the XOR
truth-table arrays) — `static const` file-scope values: named, typed,
visible in one place; no magic numbers in the logic below.

```cpp
static void output_delta(const Network &net, const std::vector<double> &y,
                         std::vector<double> &delta) {
    const Layer &out = net.layers.back();
    for (int j = 0; j < n; j++)
        delta[j] = mse_prime(out.a[j], y[j], n) * sigmoid_prime(out.z[j]);
}
```
`layers.back()` = last element of the vector. This ten-liner is the whole
"loss meets network" glue for Stage 1 — dL/da times da/dz, the chain rule
spelled out where you can see it (compare: Stage 2 uses `softmax_ce_delta`).

```cpp
static double train_epoch(Network &net) {
    int idx[4] = {0, 1, 2, 3};
    for (int i = 3; i > 0; i--) {
        int j = static_cast<int>(nn_rand_u32() % (i + 1));
        int t = idx[i]; idx[i] = idx[j]; idx[j] = t;
    }
```
**Fisher-Yates shuffle**: walk i from the end down; swap slot i with a
random slot in 0..i. Each of the 4! orderings comes out equally likely
(modulo the negligible bias from I.8), in linear time, in place. The
three-assignment swap through temporary `t` is the classic idiom.

The per-sample loop then does the canonical cycle — forward, measure,
delta, backward, `update(ETA, 1)` (batch of one = pure SGD) — and returns
the mean loss so `main`'s loop can both report and decide to stop:

```cpp
    for (int epoch = 1; epoch <= MAX_EPOCHS; epoch++) {
        double m = train_epoch(net);
        if (epoch % 1000 == 0) std::printf("epoch %5d  mse %.6f\n", epoch, m);
        if (m < TARGET_MSE) { ...; break; }
    }
```
`epoch % 1000 == 0` — remainder as a "every N-th time" gate. `break` exits
the loop early on convergence; `MAX_EPOCHS` bounds it if a bad seed never
converges (educational honesty: loops must provably end).

**The trace functions** (`trace_params`, `trace_forward`, `trace_backward`,
`trace_update`) contain no new machinery — they are printf choreography
around the same library calls, reading the caches (`ly.z`, `ly.a`,
`ly.delta`, `ly.dW`) that forward/backward leave behind. Two details worth
noticing:

- They call the REAL `net.forward`/`net.backward`/`net.update` and print
  from the real caches — the trace can't lie or drift from the library,
  because it *is* the library, narrated.
- `trace_update` must show old-value, gradient, and new-value on one line,
  but `update()` overwrites the weights and zeroes the gradients. So it
  snapshots first: `oldW.push_back(ly.W)` — vector copies (I.6) of every
  layer's W, b, dW, db — then updates, then prints all three columns.
  Memory-for-clarity, acceptable at 17 parameters.

The `--trace` branch in `main` runs `run_trace` on the freshly constructed
(never-trained) network and `return 0`s — trace shows the FIRST step, where
you can still reproduce the initial weights from the printout.

## II.8 `src/main_mnist.cpp` — Stage 2 program

### Options and parsing

```cpp
struct Options {
    unsigned int seed = 42;
    const char *save_path = NULL, *load_path = NULL;
    int predict_idx = -1;
    bool do_eval = false;
};
static bool parse_args(int argc, char **argv, Options &opt) { ... }
```
All CLI state in one struct with safe defaults (`-1` = "no predict
requested" — a sentinel value, fine here because no real index is
negative). The parser is the strcmp-walk described in I.9; unknown flags
print a usage line to stderr and return false, which `main` turns into exit
code 1.

### `evaluate`

```cpp
    std::vector<double> x(N_IN);
    for (int s = 0; s < test.n; s++) {
        std::memcpy(x.data(), &test.images[static_cast<size_t>(s) * N_IN],
                    N_IN * sizeof(double));
        const std::vector<double> &a = net.forward(x);
        int best = 0;
        for (int j = 1; j < N_OUT; j++)
            if (a[j] > a[best]) best = j;
        if (best == test.labels[s]) correct++;
    }
    return 100.0 * correct / test.n;
```
- The `x` buffer is allocated ONCE before the loop and refilled per sample —
  `memcpy` of 784 doubles (note: `* sizeof(double)` — memcpy counts BYTES).
  `&test.images[s * N_IN]` is the address of sample s's first pixel inside
  the one flat image block.
- The argmax scan: start assuming class 0 is best, challenge with each other
  class. No sorting, one pass.
- `100.0 * correct / test.n` — evaluation order matters: `100.0 * correct`
  promotes to double FIRST, so the division is floating-point. Writing
  `correct / test.n * 100.0` would integer-divide to 0 — a classic bug this
  ordering avoids.

### `train`

The epoch loop combines everything already explained: a 60000-element index
vector, Fisher-Yates per epoch, and per batch:

```cpp
        for (int start = 0; start < train_d.n; start += BATCH) {
            int batch_n = (start + BATCH <= train_d.n) ? BATCH : train_d.n - start;
            for (int k = 0; k < batch_n; k++) {
                int s = idx[start + k];
                std::memcpy(x.data(), ..., N_IN * sizeof(double));
                y[train_d.labels[s]] = 1.0;
                const std::vector<double> &a = net.forward(x);
                epoch_loss += cross_entropy(a, y);
                softmax_ce_delta(a, y, delta);
                net.backward(x, delta);
                y[train_d.labels[s]] = 0.0;
            }
            net.update(ETA, batch_n);
        }
```
- `batch_n` handles the ragged last batch: 60000 = 937×64 + 32, so the last
  batch has 32 samples and `update` divides by 32, not 64 — averaging stays
  honest.
- **The one-hot trick**: `y` is a 10-double vector of zeros created once.
  Set the true class's slot to 1.0, use it, set it back to 0.0. Cost: two
  writes per sample instead of ten (a full `assign`) — and it teaches an
  invariant-restoration pattern. (If an exception were thrown between the
  two writes the invariant would break — nothing here throws, but that is
  the kind of question to ask of this pattern in bigger systems.)
- The timing line: `static_cast<double>(std::clock() - t0) / CLOCKS_PER_SEC`
  — tick difference to seconds (I.9); measured across the whole training so
  the printed `elapsed` is cumulative.

### `save_weights` / `load_weights`

```cpp
    std::fwrite("NNC1", 1, 4, f);
    std::fwrite(&n_layers, sizeof(int), 1, f);
    for (const Layer &ly : net.layers) {
        int act = static_cast<int>(ly.act);
        std::fwrite(&ly.in, sizeof(int), 1, f);
        ...
        std::fwrite(ly.W.data(), sizeof(double), ly.W.size(), f);
```
A binary format at its most elementary: a 4-byte magic string ("is this
even our kind of file?"), the layer count, then per layer three ints of
shape metadata followed by the raw bytes of W and b straight out of the
vectors' contiguous storage. `&n_layers` — fwrite wants a memory address,
so we take the int's address and write `sizeof(int)` bytes from it. No
endianness handling here, deliberately: the file is documented as
same-machine (unlike the IDX loader, which must read files produced
elsewhere — compare and understand *when* portability is worth its cost).

Loading mirrors it with one long `&&` chain (short-circuit, I.9) that
simultaneously reads and validates — magic, layer count, then per layer:
dims and activation must EQUAL the constructed network's (`in == ly.in
&& ...`), then the raw doubles land directly in `ly.W.data()`. Any failure
anywhere → `ok` false → one error message, return false. The load-time
validation is what makes `--load garbage.bin` a clean error instead of a
network full of nonsense.

### `predict_one`

```cpp
    static const char RAMP[] = " .:-=+*#%@";
    ...
            std::putchar(RAMP[static_cast<int>(x[r * test.cols + c] * 9.99)]);
```
Ten characters ordered by visual "ink density". A pixel in [0,1] times 9.99
truncates (I.2) to an index 0..9 — the 9.99 (not 10.0) ensures a pure-white
1.0 pixel maps to index 9, not out-of-bounds 10. `r * cols + c` is the same
row-major flattening as the weight matrices — the 2D image lives in a 1D
block, and this formula is the bridge.

### `main`'s two modes

The `--load` branch constructs the network (untrained), overwrites its
weights from the file, and never touches training data — which is why
`--eval` is instant. `if (opt.do_eval || opt.predict_idx < 0)` makes bare
`--load w.bin` default to something useful (an eval) instead of silently
doing nothing. The training branch loads both datasets, reports shapes,
trains, and optionally saves. Every failure path has already printed its
own explanation by the time `return 1` runs — main never needs to guess
what went wrong.

---

# PART III — Cross-cutting things to notice

**The dependency graph is a straight line.** `activations` and `loss` know
nothing but math; `nn` knows activations (not losses!); `data_mnist` knows
nothing of networks; the two `main`s glue one loss + the network + (for
MNIST) the data. You can read any file knowing only the files above it in
this list.

**Where each requirement physically lives.** Reproducibility = the 8-line
PRNG + every random act flowing through it. Memory discipline = layer_init
(the only place vectors get sized) + RAII. Batch support = one `+=` in
backward and one `/ batch_size` in update. Numerical safety = three spots:
softmax's max-subtraction, cross-entropy's clamp, gradcheck's fmax floor.
If you can point at these, you own the codebase.

**What is deliberately absent.** No classes with private members, no
templates, no exceptions, no iterators beyond `[]`, no `auto`, no smart
pointers — not because they are bad, but because each would put a layer of
indirection between you and the math. When you meet them in real codebases,
they will be wrapping loops exactly like these.

**Suggested reading order for self-study:**
1. `activations.cpp` + `loss.cpp` (pure functions, no state)
2. `nn.hpp` (the data model) then `nn.cpp` top to bottom
3. `gradcheck.cpp` (how we know 1-2 are right)
4. `main_xor.cpp`, run `./xor --trace` beside it
5. `data_mnist.cpp` (file formats, endianness)
6. `main_mnist.cpp` (scale + the CLI/persistence glue)
