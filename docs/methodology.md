# DAMOV2 methodology & algorithms

This document specifies exactly what the DAMOV2 tools compute, so results are
reproducible and the mapping to the DAMOV paper (arXiv:2105.03725) is explicit.

## Step 1 — Memory-bound function identification

Unchanged from DAMOV: run the application natively (the `damov_hooks.h` hooks
compile to no-ops off-simulator) under Intel VTune top-down analysis and keep
functions with **Memory Bound > 30%** that take **≥ 3%** of clock cycles.
Annotate each kept function's region of interest with `damov_function_begin()` /
`damov_function_end()` and the whole hot region with `damov_roi_begin/end()`.

DAMOV2 does not automate VTune (it is proprietary and host-specific); it consumes
the *outcome* — an ROI-annotated binary.

## Step 2 — Locality-based clustering (architecture-independent)

`damov-locality` consumes a memory-reference trace (from gem5's CommMonitor,
placed after the caches so it sees the DRAM-bound reference stream) and computes
two metrics at a configurable address granularity (default: 8-byte *word*, per
the paper's footnote on word-granularity analysis).

### Spatial locality (paper Eq. 1)

Tumbling windows of `W` references (default 64). Within each window, the stride
is the **minimum absolute distance between any two distinct (quantized)
addresses**. Windows are histogrammed into `stride_profile(i)` (the fraction of
windows whose minimum stride is `i`). Then

```
SpatialLocality = Σ_i  stride_profile(i) / i        ∈ [0, 1]
```

- Sequential word accesses → quantized stride 1 → **1.0**.
- Constant byte-stride of 2 → **0.5**.
- Large/irregular strides → near **0**.

Windows of all-identical addresses (no distinct pair) contribute nothing.

### Temporal locality (paper Eq. 2)

Tumbling windows of `L` references (default 64). Within a window, an address
occurring `c` times has `N = c − 1` reuses; addresses touched once (`N = 0`) are
ignored. Each reused address increments `reuse_profile(⌊log₂ N⌋)`
(`N=1`→bin 0 "reused once", `N=2..3`→bin 1 "reused twice", …). Then

```
TemporalLocality = Σ_i  2^i · reuse_profile(i) / total_accesses     ∈ [0, 1]
```

- All-unique stream → **0** (no reuse).
- A single address hammered → high (the power-of-2 binning of Eq. 2 undershoots
  the ideal by up to 2×, so an all-reuse window of size 64 scores ≈ 0.5). The
  validated threshold (0.48) is calibrated to this exact formula.

Window sizes and granularity are configurable; the paper reports the low/high
clustering is stable across `W, L ∈ {8,16,32,64,128}`.

## Step 3 — Bottleneck classification (scalability analysis)

For each function, gem5 + Ramulator2 run the three system configurations
(`host_ooo`, `host_prefetch`, `ndp`) across core counts `{1,4,16,64,256}`.
`damov-stats` derives, from each run's `stats.txt` (+ Ramulator2 stats):

| Metric | Definition | gem5 stats used (default patterns) |
|--------|-----------|-------------------------------------|
| IPC  | instructions / cycles | `simInsts`, `numCycles` |
| MPKI | LLC misses per 1000 instructions | `l3.overallMisses::total` |
| LFMR | LLC misses / total L1 misses | `l3…` / (`dcache…` + `icache…` misses) |
| AI   | arithmetic ops per L1 access | `committedInstType::IntAlu`+FP / `dcache.overallAccesses` |

Stat name patterns are configurable (`StatPatterns::fromFile`) to track gem5
version differences.

`damov-classify` then applies the six-class decision tree (paper Fig. 26) using
the temporal locality from Step 2 and the AI/MPKI/LFMR sweep from Step 3:

```
Temporal locality < 0.48  (LOW)
    LFMR decreasing across cores          -> 1a? no -> 1c  L1/L2 cache capacity
    LFMR high & ~constant
        MPKI > 11   -> 1a  DRAM bandwidth
        MPKI ≤ 11   -> 1b  DRAM latency
Temporal locality ≥ 0.48  (HIGH)
    LFMR increasing across cores          -> 2a  L3 cache contention
    LFMR low & ~constant
        AI > 8.5    -> 2c  compute-bound
        AI ≤ 8.5    -> 2b  L1 cache capacity
```

Validated thresholds (paper §3.5.1): temporal locality `0.48`, LFMR `0.56`,
MPKI `11.0`, AI `8.5`. The LFMR trend is "increasing"/"decreasing" when the
change from the lowest to the highest core count exceeds `trend_delta` (0.10),
else "constant". These are the two architecture-dependent trends (1c decreasing,
2a increasing) the paper relies on.

### Why the highest core count is the representative operating point

Bandwidth saturation (1a) and cache contention (2a) only manifest at scale, so
`damov-classify` reads the scalar AI/MPKI/LFMR from the highest-core-count run
while using the whole sweep to determine the LFMR trend. This matches the
paper's observations that Class 1a functions saturate DRAM bandwidth near 64
cores and Class 2a functions become contention-bound at 256 cores.

The shipped [configs/damov.yaml](../configs/damov.yaml) caps the default sweep
at `{1,4,16,64}`: a 256-core out-of-order run needs ~60 GB+ of host RAM and OOMs
on typical machines, and 64 cores already captures Class 1a bandwidth
saturation. The 256-core point is therefore opt-in — add it back to `cores:` on
a large-memory host or cluster when you need faithful **Class 2a** (L3
contention) classification, which only manifests at that scale.

## Differences from the original DAMOV that affect numbers

1. **Simulators**: gem5 (vs ZSim) and Ramulator2 (vs Ramulator v1). Absolute
   IPC/energy will differ; the *classification* depends on ratios (LFMR, MPKI,
   AI, temporal locality) and thresholds, which are simulator-robust — the paper
   itself shows the classes are stable across in-order/out-of-order cores.
2. **3D-stacked memory**: HMC v2 is modeled with HBM2 in Ramulator2 (HMC is not
   a Ramulator2 standard). Bank/vault parallelism and ~8 GB capacity are matched
   in `gem5/ramulator2/HMC-config.yaml`.
3. **Locality windows/granularity** are explicit, documented parameters here
   (`configs/damov.yaml`), whereas the original hard-coded them in Python.
