#ifndef ACTIVATIONS_HPP
#define ACTIVATIONS_HPP

#include <vector>

/* Scalar activations, each next to its derivative (SRS 1.3-3). */
double sigmoid(double z);        /* s(z) = 1 / (1 + e^-z)            */
double sigmoid_prime(double z);  /* s'(z) = s(z) * (1 - s(z))        */
double relu(double z);           /* r(z) = max(0, z)                 */
double relu_prime(double z);     /* r'(z) = z > 0 ? 1 : 0            */

/* Vector activation: a_j = e^{z_j} / sum_k e^{z_k}.
 * Uses the max-subtraction trick for numerical stability.
 * Its "derivative" never appears alone: combined with cross-entropy the
 * output delta collapses to (a - y) — see loss.hpp and EXPLANATION.md. */
void softmax(const std::vector<double> &z, std::vector<double> &a);

#endif
