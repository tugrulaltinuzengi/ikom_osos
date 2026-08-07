#ifndef LOSS_HPP
#define LOSS_HPP

#include <vector>

/* Stage 1 loss: MSE.  L = (1/n) * sum_j (a_j - y_j)^2
 * Derivative used to start backprop:  dL/da_j = 2 * (a_j - y_j) / n   */
double mse(const std::vector<double> &a, const std::vector<double> &y);
double mse_prime(double a_j, double y_j, int n);

/* Stage 2 loss: cross-entropy over a softmax output.
 * L = - sum_j y_j * log(a_j)     (y is one-hot)                       */
double cross_entropy(const std::vector<double> &a, const std::vector<double> &y);

/* Combined softmax + cross-entropy shortcut (derived in EXPLANATION.md):
 * delta_j = dL/dz_j = a_j - y_j  — this starts backprop for Stage 2.  */
void softmax_ce_delta(const std::vector<double> &a, const std::vector<double> &y,
                      std::vector<double> &delta);

#endif
