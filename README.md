# DAMOV2 — A Modern Data-Movement Bottleneck Analysis Framework

DAMOV2 is a modernized, from-scratch reimplementation of the
[DAMOV](https://github.com/CMU-SAFARI/DAMOV) methodology and toolchain described in:

> G. F. Oliveira, J. Gómez-Luna, L. Orosa, S. Ghose, N. Vijaykumar, I. Fernandez,
> M. Sadrosadati, O. Mutlu, *"DAMOV: A New Methodology and Benchmark Suite for
> Evaluating Data Movement Bottlenecks"*, arXiv:2105.03725.

DAMOV characterizes the **primary source of a memory (data-movement) bottleneck**
for each hot function of an application and classifies it into one of six
bottleneck classes, so that the right mitigation (deep cache hierarchy, hardware
prefetcher, or Near-Data Processing / PIM) can be chosen.

## What changed versus the original DAMOV

| Component                         | Original DAMOV        | DAMOV2 (this repo)          |
|-----------------------------------|-----------------------|-----------------------------|
| CPU / cache-hierarchy simulator   | ZSim (Pin-based)      | **gem5**                    |
| DRAM / memory simulator           | Ramulator (v1)        | **Ramulator2**              |
| Region-of-interest hooks          | `zsim_hooks.h`        | `hooks/damov_hooks.h` (m5ops) |
| Locality analysis                 | Python + ZSim traces  | `damov-locality` (C++17)    |
| Metric extraction / classification| Python scripts        | `damov-stats` / `damov-classify` (C++17) |
| Config generation / orchestration | Python (ZSim `.cfg`)  | Python (gem5 SE + Ramulator2 YAML) |

The DAMOV *methodology* is preserved exactly (same metrics, same six-class
decision tree); only the simulators and the surrounding tooling are modernized.

## The three-step methodology

```
         ┌──────────────────────────────────────────────────────────────┐
         │  Step 1  Memory-bound function identification                 │
         │          (Intel VTune top-down: Memory Bound > 30%)           │
         │          → annotate hot functions with damov_hooks.h ROIs      │
         └──────────────────────────────────────────────────────────────┘
                                   │  ROI-annotated binary
         ┌─────────────────────────┴────────────────────────────────────┐
         │  Step 2  Locality-based clustering (architecture-independent) │
         │   gem5 CommMonitor → memory trace → damov-locality            │
         │   → Spatial Locality (Eq.1), Temporal Locality (Eq.2)          │
         └──────────────────────────────────────────────────────────────┘
                                   │  temporal locality
         ┌─────────────────────────┴────────────────────────────────────┐
         │  Step 3  Bottleneck classification (scalability analysis)     │
         │   gem5 + Ramulator2 over {1,4,16,64,256} cores × 3 configs    │
         │     (host_ooo, host_prefetch, ndp)                            │
         │   damov-stats  → AI, MPKI, LFMR per (function, cores, config)  │
         │   damov-classify → one of {1a,1b,1c,2a,2b,2c}                  │
         └──────────────────────────────────────────────────────────────┘
```

### The six memory-bottleneck classes (Fig. 26 of the paper)

| Class | Temporal locality | LFMR            | MPKI | AI   | Bottleneck              | Best mitigation |
|-------|-------------------|-----------------|------|------|-------------------------|-----------------|
| 1a    | low               | high            | high | low  | DRAM bandwidth          | NDP             |
| 1b    | low               | high            | low  | low  | DRAM latency            | NDP             |
| 1c    | low               | decreasing/cores| low  | low  | L1/L2 cache capacity    | deep cache @ high cores |
| 2a    | high              | increasing/cores| low  | low  | L3 cache contention     | NDP (cheaper than bigger L3) |
| 2b    | high              | low             | low  | low  | L1 cache capacity       | either (no penalty) |
| 2c    | high              | low             | low  | high | compute-bound           | deep cache + prefetcher |

Validated thresholds (paper §3.5.1): temporal locality `0.48`, LFMR `0.56`,
MPKI `11.0`, AI `8.5`.

## Repository layout

```
damov2/
├── hooks/damov_hooks.h        # ROI markers for workloads (gem5 m5ops)
├── include/damov/             # C++17 core library public headers
├── src/                       # C++17 core library + CLI tools
│   ├── trace/                 # memory-trace reader
│   ├── locality/              # Step 2: spatial/temporal locality (Eq.1/Eq.2)
│   ├── metrics/               # AI / MPKI / LFMR extraction from sim stats
│   ├── classify/              # Step 3: six-class decision tree
│   └── cli/                   # damov-locality, damov-stats, damov-classify
├── gem5/
│   ├── configs/               # gem5 SE-mode system + Ramulator2 config builder
│   └── ramulator2/            # Ramulator2 DSL memory configs (hmc.py, ddr4.py)
├── external/                  # git submodules (pinned simulators)
│   ├── gem5/                  #   github.com/gem5/gem5
│   └── ramulator2/            #   github.com/CMU-SAFARI/ramulator2
├── scripts/                   # setup, config generation, run driver, collection
├── slurm/                     # SLURM cluster job scripts
├── workloads/STREAM/          # instrumented example workload
├── configs/damov.yaml         # global config (core counts, thresholds, paths)
├── tests/                     # unit tests (locality, classify, metrics)
└── docs/methodology.md        # detailed algorithm/metric documentation
```

## Building the C++ toolchain

Requires CMake ≥ 3.16 and a C++17 compiler.

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build          # run unit tests
```

This produces three binaries under `build/`:

- `damov-locality` — Step 2 locality analysis of a memory trace
- `damov-stats`    — parse gem5 + Ramulator2 stats into AI/MPKI/LFMR/IPC
- `damov-classify` — Step 3 bottleneck classification

## Simulator prerequisites (submodules)

gem5 and Ramulator2 are vendored as git **submodules** under `external/` and
pinned to known-good versions:

```bash
git submodule update --init --depth 1 external/ramulator2 external/gem5
scripts/setup_gem5_ramulator2.sh X86 $(nproc)   # builds both + wires them together
```

`setup_gem5_ramulator2.sh` builds Ramulator2 (`libramulator.so`), installs its
gem5 wrapper into `external/gem5/src/mem/ramulator2/`, and builds
`external/gem5/build/X86/gem5.opt`. See [gem5/README.md](gem5/README.md) for what
it does and how DAMOV2 selects a memory model (`--ramulator-config hmc|ddr4|…`).

## Quick start (end-to-end for one function)

```bash
# 0. Build the C++ tools, and (once) the simulators
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
scripts/setup_gem5_ramulator2.sh                # gem5 + Ramulator2 submodules

# 1. Build the instrumented workload (ROI hooks + m5ops)
make -C workloads/STREAM GEM5_ROOT=external/gem5

# 2. Plan + Step 2 (trace) + Step 3 (scalability sweep) via the pipeline
python scripts/damov2_pipeline.py --descriptor benchmarks/stream.yaml
# → per-function report, e.g. STREAM Add:
#   class 1a (DRAM bandwidth); mitigation: NDP

# …or run the stages by hand:
python scripts/generate_configs.py --descriptor benchmarks/stream.yaml
python scripts/run_experiment.py   --plan out/stream/plan.json --stage trace
python scripts/run_experiment.py   --plan out/stream/plan.json --stage scale
python scripts/collect_stats.py    --suite stream --function Add
build/damov-classify --metrics out/stream/Add.metrics.csv \
       --locality out/stream/Add.locality.csv --pretty
```

On a cluster, use the SLURM scripts instead — see [slurm/README.md](slurm/README.md).

## License

Released under the MIT License (see `LICENSE`). The DAMOV methodology is due to
the SAFARI Research Group; this is an independent modernized reimplementation.
