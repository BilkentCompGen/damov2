/*
 * hello_damov.c — the DAMOV2 "hello world" workload.
 *
 * A minimal ROI-annotated application whose job is to prove the DAMOV2
 * toolchain works end to end. It contains two hot functions with deliberately
 * *opposite* locality, so the expected DAMOV answer is known in advance:
 *
 *   stream : c[i] = a[i] + b[i] over a large array.
 *            Sequential, zero reuse  -> spatial ~1.0, temporal ~0.0 (LOW)
 *            -> Class 1x (a DRAM bottleneck; NDP is the right mitigation)
 *
 *   reuse  : repeatedly sum a tiny working set that fits in L1.
 *            Same addresses over and over -> temporal locality HIGH
 *            -> Class 2x (a cache/compute bottleneck, not a DRAM one)
 *
 * Usage:
 *   hello_damov stream [n]            # n = elements   (default 4096)
 *   hello_damov reuse  [n] [passes]   # n = working set (default 8, 1024)
 *
 * Three build flavors (see the Makefile); the ROI hooks are what differ:
 *
 *   make native   -> hooks compile to no-ops; runs on real hardware (Step 1)
 *   make trace    -> additionally self-dumps its memory trace (Step 2 input)
 *   make gem5     -> real m5ops; for detailed gem5 + Ramulator2 simulation
 *
 * The `trace` flavor exists so Step 2 (locality) can be exercised without a
 * simulator: the program reports the exact addresses its kernels touch in the
 * text format `damov-locality` reads. Set the output path with
 * DAMOV_TRACE_FILE (default: hello_trace.txt).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "damov_hooks.h"

/* ---------------------------------------------------------------------------
 * Self-tracing (only in the `trace` flavor). Emits DAMOV2 trace lines:
 *     R 0x7ffd0040 8
 * which is format 2 of damov::TraceReader ("type address size").
 * ------------------------------------------------------------------------- */
#ifdef DAMOV_SELF_TRACE

static FILE *g_trace = NULL;

static void trace_open(void)
{
    const char *path = getenv("DAMOV_TRACE_FILE");
    if (!path) path = "hello_trace.txt";
    g_trace = fopen(path, "w");
    if (!g_trace) {
        perror("hello_damov: cannot open DAMOV_TRACE_FILE");
        exit(1);
    }
    fprintf(stderr, "hello_damov: writing memory trace to %s\n", path);
}

static void trace_close(void)
{
    if (g_trace) { fclose(g_trace); g_trace = NULL; }
}

#define TRACE_ACCESS(kind, ptr)                                              \
    do {                                                                     \
        if (g_trace)                                                         \
            fprintf(g_trace, kind " 0x%llx 8\n",                             \
                    (unsigned long long)(uintptr_t)(ptr));                   \
    } while (0)

#define TRACE_R(ptr) TRACE_ACCESS("R", ptr)
#define TRACE_W(ptr) TRACE_ACCESS("W", ptr)

#else  /* not self-tracing: zero overhead, identical kernels */

static void trace_open(void) {}
static void trace_close(void) {}
#define TRACE_R(ptr) ((void)0)
#define TRACE_W(ptr) ((void)0)

#endif

/* ---------------------------------------------------------------------------
 * Kernel "stream": streaming add. No reuse, perfectly sequential.
 * ------------------------------------------------------------------------- */
static void kernel_stream(double *a, double *b, double *c, size_t n)
{
    damov_function_begin();
    for (size_t i = 0; i < n; i++) {
        TRACE_R(&a[i]);
        TRACE_R(&b[i]);
        c[i] = a[i] + b[i];
        TRACE_W(&c[i]);
    }
    damov_function_end();
}

/* ---------------------------------------------------------------------------
 * Kernel "reuse": hammer a tiny working set. Maximum temporal locality.
 * ------------------------------------------------------------------------- */
static double kernel_reuse(const double *a, size_t working_set, size_t passes)
{
    double sum = 0.0;
    damov_function_begin();
    for (size_t p = 0; p < passes; p++) {
        for (size_t i = 0; i < working_set; i++) {
            TRACE_R(&a[i]);
            sum += a[i];
        }
    }
    damov_function_end();
    return sum;
}

static void usage(const char *prog)
{
    fprintf(stderr,
            "Usage: %s stream [n]\n"
            "       %s reuse  [working_set] [passes]\n",
            prog, prog);
}

int main(int argc, char **argv)
{
    printf("hello, DAMOV2\n");

    if (argc < 2) { usage(argv[0]); return 2; }
    const char *kernel = argv[1];

    trace_open();

    if (strcmp(kernel, "stream") == 0) {
        size_t n = (argc > 2) ? (size_t)strtoull(argv[2], NULL, 10) : 4096;
        double *a = malloc(n * sizeof *a);
        double *b = malloc(n * sizeof *b);
        double *c = malloc(n * sizeof *c);
        if (!a || !b || !c) { fprintf(stderr, "out of memory\n"); return 1; }
        for (size_t i = 0; i < n; i++) { a[i] = (double)i; b[i] = 2.0; }

        damov_roi_begin();
        kernel_stream(a, b, c, n);
        damov_roi_end();

        printf("stream: n=%zu c[0]=%.1f c[%zu]=%.1f\n", n, c[0], n - 1, c[n - 1]);
        free(a); free(b); free(c);

    } else if (strcmp(kernel, "reuse") == 0) {
        size_t ws     = (argc > 2) ? (size_t)strtoull(argv[2], NULL, 10) : 8;
        size_t passes = (argc > 3) ? (size_t)strtoull(argv[3], NULL, 10) : 1024;
        double *a = malloc(ws * sizeof *a);
        if (!a) { fprintf(stderr, "out of memory\n"); return 1; }
        for (size_t i = 0; i < ws; i++) a[i] = 1.0;

        damov_roi_begin();
        double sum = kernel_reuse(a, ws, passes);
        damov_roi_end();

        printf("reuse: working_set=%zu passes=%zu sum=%.1f\n", ws, passes, sum);
        free(a);

    } else {
        usage(argv[0]);
        trace_close();
        return 2;
    }

    trace_close();
    return 0;
}
