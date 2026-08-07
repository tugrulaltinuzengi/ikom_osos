#include <cmath>
#include "activations.hpp"

/* s(z) = 1 / (1 + e^-z) */
double sigmoid(double z) {
    return 1.0 / (1.0 + std::exp(-z));
}

/* s'(z) = s(z) * (1 - s(z)) */
double sigmoid_prime(double z) {
    double s = sigmoid(z);
    return s * (1.0 - s);
}

/* r(z) = max(0, z) */
double relu(double z) {
    return z > 0.0 ? z : 0.0;
}

/* r'(z) = z > 0 ? 1 : 0 */
double relu_prime(double z) {
    return z > 0.0 ? 1.0 : 0.0;
}

/* a_j = e^{z_j - m} / sum_k e^{z_k - m}, where m = max(z) is subtracted
 * from every entry first so the largest exponent is e^0 = 1 — this keeps
 * exp() from overflowing on large inputs (the max-subtraction trick). */
void softmax(const std::vector<double> &z, std::vector<double> &a) {
    int n = static_cast<int>(z.size());

    double m = z[0];
    for (int j = 1; j < n; j++)   /* m = max_k z_k */
        if (z[j] > m)
            m = z[j];

    double sum = 0.0;
    for (int j = 0; j < n; j++) { /* a_j = e^{z_j - m}, accumulate sum_k e^{z_k - m} */
        a[j] = std::exp(z[j] - m);
        sum += a[j];
    }

    for (int j = 0; j < n; j++)   /* a_j = a_j / sum */
        a[j] /= sum;
}
