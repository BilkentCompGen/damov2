/*
 * zsim_hooks.h — DAMOV-compatibility shim for DAMOV2.
 *
 * Workloads instrumented for the original DAMOV (ZSim) call the zsim_* hooks
 * from DAMOV's `zsim_hooks.h`. This header provides the same API on top of
 * DAMOV2's `damov_hooks.h`, so those sources rebuild for gem5 unchanged:
 *
 *     cc -O2 -I<damov2>/hooks/compat -I<damov2>/hooks -I<gem5>/include \
 *        -DDAMOV_USE_M5OPS app.c -L<gem5>/util/m5/build/x86/out -lm5
 *
 * The backend is chosen exactly as for damov_hooks.h (-DDAMOV_USE_M5OPS,
 * -DDAMOV_USE_MAGIC, or nothing for native no-op hooks).
 *
 * Mapping (see docs/migrating-from-damov.md):
 *
 *     zsim_roi_begin()           -> damov_roi_begin()
 *     zsim_roi_end()             -> damov_roi_end()
 *     zsim_PIM_function_begin()  -> damov_function_begin()
 *     zsim_PIM_function_end()    -> damov_function_end()
 *     zsim_begin() / zsim_end()  -> both of the above, in DAMOV's order
 *     zsim_heartbeat()           -> no-op (no gem5 equivalent is needed)
 *     zsim_work_begin/end()      -> no-op (ZSim/ubik work units; DAMOV2's work
 *                                   ids 100/101 are reserved for the ROI and
 *                                   function markers above)
 *
 * IMPORTANT: a binary built against DAMOV's own zsim_hooks.h emits ZSim's
 * `xchg %rcx, %rcx` magic ops, which gem5 executes as plain NOPs — the ROI is
 * never seen and the detailed CPU never switches in. Every workload must be
 * rebuilt against this shim (or ported to damov_hooks.h). If a workload keeps
 * a private copy of zsim_hooks.h next to its sources, `#include "zsim_hooks.h"`
 * finds that copy first; delete it or replace it with this file.
 */
#ifndef __ZSIM_HOOKS_H__
#define __ZSIM_HOOKS_H__
#define DAMOV2_ZSIM_COMPAT 1

#include "../damov_hooks.h"

static inline void zsim_roi_begin(void)
{
    damov_roi_begin();
}

static inline void zsim_roi_end(void)
{
    damov_roi_end();
}

static inline void zsim_PIM_function_begin(void)
{
    damov_function_begin();
}

static inline void zsim_PIM_function_end(void)
{
    damov_function_end();
}

static inline void zsim_begin(void)
{
    zsim_roi_begin();
    zsim_PIM_function_begin();
}

static inline void zsim_end(void)
{
    zsim_PIM_function_end();
    zsim_roi_end();
}

static inline void zsim_heartbeat(void) {}
static inline void zsim_work_begin(void) {}
static inline void zsim_work_end(void) {}

#endif /* __ZSIM_HOOKS_H__ */
