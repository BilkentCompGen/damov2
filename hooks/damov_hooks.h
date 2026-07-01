/*
 * damov_hooks.h — DAMOV2 region-of-interest (ROI) instrumentation hooks.
 *
 * Modern replacement for the original DAMOV `zsim_hooks.h`. Instead of ZSim's
 * magic NOP sequences, DAMOV2 uses gem5's "m5ops" magic instructions so that
 * gem5 can (a) delimit the region of interest, (b) switch to the detailed
 * (timing/O3) CPU + Ramulator2 memory model only for the hot region, and
 * (c) reset/dump statistics around each offloadable function.
 *
 * Usage in a workload:
 *
 *     #include "damov_hooks.h"
 *     ...
 *     damov_roi_begin();              // start of the region of interest
 *       ...
 *       damov_function_begin();       // start of an NDP-offloadable function
 *         hot_kernel();
 *       damov_function_end();         // end of the offloadable function
 *       ...
 *     damov_roi_end();                // end of the region of interest
 *
 * Build/link:
 *   - Detailed simulation (default): compile with -DDAMOV_USE_M5OPS and link
 *     against gem5's libm5 (util/m5/): `-I<gem5>/include -L<gem5>/util/m5/build/x86/out -lm5`.
 *   - Native run (no simulator): compile with nothing special; all hooks become
 *     no-ops so the exact same binary runs on real hardware for Step-1 profiling
 *     (e.g. under Intel VTune top-down analysis).
 *   - Fallback magic ops: compile with -DDAMOV_USE_MAGIC to emit the raw m5op
 *     magic instruction encodings inline without libm5 (useful in SE mode when
 *     you cannot link libm5).
 *
 * The three m5 operations we rely on:
 *   m5_work_begin(id, flags) / m5_work_end(id, flags) — gem5 uses these to
 *       trigger a CPU switch (atomic→O3/timing) and warm-up, driven by
 *       `--work-begin-cpu-switch`. We map ROI + function begins to work_begin
 *       so the detailed model + Ramulator2 only run inside the ROI.
 *   m5_reset_stats(delay, period) / m5_dump_stats(delay, period) — bracket the
 *       statistics we later parse with `damov-stats` so that AI/MPKI/LFMR are
 *       measured over the offloaded function only.
 *   m5_exit(0) — optional, to stop the run right after the ROI when doing
 *       trace-only or single-function characterization.
 */
#ifndef DAMOV_HOOKS_H
#define DAMOV_HOOKS_H

#ifdef __cplusplus
extern "C" {
#endif

/* ----------------------------------------------------------------------------
 * Work-item ids. gem5's --work-item-id / --work-begin-cpu-switch select which
 * work id triggers the detailed-CPU switch. Keep these stable so the gem5
 * config scripts (gem5/configs/damov_se.py) can reference them.
 * -------------------------------------------------------------------------- */
#define DAMOV_ROI_WORK_ID      100  /* whole region of interest              */
#define DAMOV_FUNCTION_WORK_ID 101  /* individual NDP-offloadable function   */

/* ============================================================================
 * Backend 1: link against gem5's libm5 (recommended, -DDAMOV_USE_M5OPS).
 * ========================================================================== */
#if defined(DAMOV_USE_M5OPS)

#include <gem5/m5ops.h>

static inline void damov_roi_begin(void) {
    m5_reset_stats(0, 0);
    m5_work_begin(DAMOV_ROI_WORK_ID, 0);
}
static inline void damov_roi_end(void) {
    m5_work_end(DAMOV_ROI_WORK_ID, 0);
    m5_dump_stats(0, 0);
}
static inline void damov_function_begin(void) {
    m5_reset_stats(0, 0);
    m5_work_begin(DAMOV_FUNCTION_WORK_ID, 0);
}
static inline void damov_function_end(void) {
    m5_work_end(DAMOV_FUNCTION_WORK_ID, 0);
    m5_dump_stats(0, 0);
}
static inline void damov_roi_exit(void) { m5_exit(0); }

/* ============================================================================
 * Backend 2: inline x86-64 m5op magic instruction encodings (-DDAMOV_USE_MAGIC).
 * Mirrors gem5's util/m5 encodings without requiring libm5 to be linked.
 * ========================================================================== */
#elif defined(DAMOV_USE_MAGIC) && (defined(__x86_64__) || defined(_M_X64))

/* gem5 x86 "magic" instruction: .word 0x040F ; .word (func<<8 | subfunc). */
#define DAMOV_M5OP(func, subfunc)                                            \
    __asm__ __volatile__(".word 0x040F; .word %c0"                          \
                         : : "i"(((func) << 8) | (subfunc))                 \
                         : "rax", "rcx", "rdx", "memory")

/* m5op function codes (see gem5 src/sim/pseudo_inst.hh) */
#define DAMOV_M5_RESET_STATS 0x40
#define DAMOV_M5_DUMP_STATS  0x41
#define DAMOV_M5_WORK_BEGIN  0x5a
#define DAMOV_M5_WORK_END    0x5b
#define DAMOV_M5_EXIT        0x21

static inline void damov_roi_begin(void) {
    DAMOV_M5OP(DAMOV_M5_RESET_STATS, 0);
    DAMOV_M5OP(DAMOV_M5_WORK_BEGIN, 0);
}
static inline void damov_roi_end(void) {
    DAMOV_M5OP(DAMOV_M5_WORK_END, 0);
    DAMOV_M5OP(DAMOV_M5_DUMP_STATS, 0);
}
static inline void damov_function_begin(void) {
    DAMOV_M5OP(DAMOV_M5_RESET_STATS, 0);
    DAMOV_M5OP(DAMOV_M5_WORK_BEGIN, 0);
}
static inline void damov_function_end(void) {
    DAMOV_M5OP(DAMOV_M5_WORK_END, 0);
    DAMOV_M5OP(DAMOV_M5_DUMP_STATS, 0);
}
static inline void damov_roi_exit(void) { DAMOV_M5OP(DAMOV_M5_EXIT, 0); }

/* ============================================================================
 * Backend 3: native / no-op. The exact same source & binary shape runs on real
 * hardware (Step 1 VTune profiling) with zero overhead.
 * ========================================================================== */
#else

static inline void damov_roi_begin(void)       {}
static inline void damov_roi_end(void)         {}
static inline void damov_function_begin(void)  {}
static inline void damov_function_end(void)    {}
static inline void damov_roi_exit(void)        {}

#endif

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* DAMOV_HOOKS_H */
