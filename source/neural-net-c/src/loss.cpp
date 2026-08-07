#include <cmath>
#include "loss.hpp"

/* L = (1/n) * sum_j (a_j - y_j)^2 */
double mse(const std::vector<double> &a, const std::vector<double> &y) {
    int n = static_cast<int>(a.size());
    double sum = 0.0;
    for (int j = 0; j < n; j++) { /* sum_j (a_j - y_j)^2 */
        double diff = a[j] - y[j];
        sum += diff * diff;
    }
    return sum / n;
}

/* dL/da_j = 2 * (a_j - y_j) / n */
double mse_prime(double a_j, double y_j, int n) {
    return 2.0 * (a_j - y_j) / n;
}

/* L = - sum_j y_j * log(a_j) */
double cross_entropy(const std::vector<double> &a, const std::vector<double> &y) {
    int n = static_cast<int>(a.size());
    double sum = 0.0;
    for (int j = 0; j < n; j++) { /* sum_j y_j * log(a_j) */
        double a_j = a[j];
        if (a_j < 1e-12)          /* clamp to avoid log(0) = -inf */
            a_j = 1e-12;
        sum += y[j] * std::log(a_j);
    }
    return -sum;
}

/* delta_j = a_j - y_j (derived from d/dz_j of softmax + cross-entropy) */
void softmax_ce_delta(const std::vector<double> &a, const std::vector<double> &y,
                      std::vector<double> &delta) {
    int n = static_cast<int>(a.size());
    for (int j = 0; j < n; j++) /* delta_j = a_j - y_j */
        delta[j] = a[j] - y[j];
}
