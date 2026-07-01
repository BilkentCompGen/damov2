#ifndef DAMOV_TEST_UTIL_HPP
#define DAMOV_TEST_UTIL_HPP

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>

static int g_failures = 0;

#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            ++g_failures;                                                    \
        }                                                                    \
    } while (0)

#define CHECK_NEAR(a, b, tol)                                                \
    do {                                                                     \
        double _a = (a), _b = (b);                                          \
        if (std::fabs(_a - _b) > (tol)) {                                    \
            std::fprintf(stderr, "FAIL %s:%d: %s=%g != %s=%g (tol %g)\n",    \
                         __FILE__, __LINE__, #a, _a, #b, _b, (double)(tol)); \
            ++g_failures;                                                    \
        }                                                                    \
    } while (0)

#define RUN_TESTS()                                                          \
    (g_failures == 0 ? (std::printf("all tests passed\n"), EXIT_SUCCESS)     \
                     : (std::fprintf(stderr, "%d failure(s)\n", g_failures), \
                        EXIT_FAILURE))

#endif  // DAMOV_TEST_UTIL_HPP
