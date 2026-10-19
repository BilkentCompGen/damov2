# CLAUDE.md

Guidance for working in this repository.

## What this is

DAMOV2 is a from-scratch reimplementation of the DAMOV data-movement bottleneck
methodology (arXiv:2105.03725), modernized to **gem5 + Ramulator2** instead of
ZSim + Ramulator v1. For each hot function of an application it measures
locality + scalability metrics and assigns one of six bottleneck classes
(1a/1b/1c/2a/2b/2c), each with a recommended mitigation (deep cache hierarchy,
prefetcher, or NDP/PIM).

The methodology is fixed and documented in [docs/methodology.md](docs/methodology.md).
Treat that file as the spec: if you change what `damov-locality`,
`damov-stats`, or `damov-classify` compute, update it in the same change.

## Build and test

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build            # 3 unit tests: locality, classify, metrics
scripts/smoke_test.sh             # 20 end-to-end checks on examples/hello
```

`scripts/smoke_test.sh` is the integration test: it drives the hello-world
workload through every stage and asserts the two kernels classify as 1a and 2b.
Stages mark themselves `[REAL]` or `[MODEL]` and **skip** (not fail) when a
prerequisite is missing, so it works without gem5 — prefer it over ad-hoc
verification after touching anything in the pipeline. [INSTALL.md](INSTALL.md)
records which prerequisites each tier needs and how to uninstall them.

C++17, CMake ≥ 3.16, `-Wall -Wextra`. No external C++ dependencies. Tests are
plain assert-based binaries (helpers in [tests/test_util.hpp](tests/test_util.hpp))
registered with CTest — a new test file must be added manually to
[tests/CMakeLists.txt](tests/CMakeLists.txt).

The Python orchestration scripts require **no third-party packages**; PyYAML is
used if importable, otherwise `damov_common._tiny_yaml` parses the restricted
subset used by the config files. Keep new YAML in `configs/` and `benchmarks/`
within that subset (nested mappings by indentation, inline lists, `- ` items —
no anchors, no multi-line flow mappings).

Simulators are git submodules, built separately and **not** part of the CMake
build:

```bash
git submodule update --init --depth 1 external/ramulator2 external/gem5
scripts/setup_gem5_ramulator2.sh X86 $(nproc)
```

## Architecture

Three layers, deliberately separated:

**1. `src/` + `include/damov/` — simulator-independent C++ core** (`damov_core`
static lib) plus three thin CLI front-ends in [src/cli/](src/cli/). Headers in
[include/damov/](include/damov/) carry the authoritative documentation of each
algorithm; read the header before the `.cpp`.

| Module | Role |
|--------|------|
| [trace.cpp](src/trace/trace.cpp) | streaming memory-trace reader (text, `.gz` via `gzip -dc`, stdin) |
| [locality.cpp](src/locality/locality.cpp) | Step 2: spatial (Eq. 1) / temporal (Eq. 2) locality, O(W+L) memory |
| [metrics.cpp](src/metrics/metrics.cpp) | Step 3 inputs: parse gem5 `stats.txt` + Ramulator2 stats → IPC/MPKI/LFMR/AI |
| [classify.cpp](src/classify/classify.cpp) | Step 3: six-class decision tree (paper Fig. 26) |

**2. `scripts/` — Python orchestration.** All share
[damov_common.py](scripts/damov_common.py) (config loading, `DAMOV2_*` env
overrides, and the canonical output layout). Data flow:

```
benchmarks/<suite>.yaml                     descriptor (functions to characterize)
  → generate_configs.py   → out/<suite>/plan.json           (job cross-product)
  → run_experiment.py     → gem5 runs      (--stage trace | scale)
  → collect_stats.py      → out/<suite>/<fn>.{metrics,locality}.csv
  → damov-classify        → class + mitigation
```

[damov2_pipeline.py](scripts/damov2_pipeline.py) runs all four in sequence.
[export_joblist.py](scripts/export_joblist.py) flattens a plan into one gem5
command per line for SLURM arrays; [proto2trace.py](scripts/proto2trace.py)
converts a gem5 protobuf packet trace to the text format `TraceReader` expects.

Output layout (from `damov_common.out_dir`, do not reinvent it):

```
out/<suite>/<function>/<config>/<cores>/   # scaling runs (stats.txt, ramulator_stats.yaml)
out/<suite>/<function>/trace/              # Step-2 trace run
```

**3. `gem5/` — gem5 configuration scripts** (not the gem5 source; that is
`external/gem5`). [damov_se.py](gem5/configs/damov_se.py) builds the three
system configurations `host_ooo` / `host_prefetch` / `ndp` (Table 1 of the
paper), handles the ROI CPU switch, and optionally dumps a memory trace;
[ramulator2_mem.py](gem5/configs/ramulator2_mem.py) turns a preset name or DSL
file into the JSON `ramulator_config` string the Ramulator2 SimObject takes.
See [gem5/README.md](gem5/README.md) for the integration details.

`hooks/damov_hooks.h` is the workload-side ROI API (`damov_roi_begin/end`,
`damov_function_begin/end`) with three backends: libm5 (`-DDAMOV_USE_M5OPS`),
inline x86 magic ops (`-DDAMOV_USE_MAGIC`), and no-ops (native Step-1
profiling). The work IDs `DAMOV_ROI_WORK_ID` / `DAMOV_FUNCTION_WORK_ID` are a
contract with `damov_se.py` — changing one requires changing the other.

## Conventions and things that bite

- **Thresholds are duplicated by design.** The validated values (temporal
  locality 0.48, LFMR 0.56, MPKI 11.0, AI 8.5, trend delta 0.10) appear as C++
  defaults in `ClassifyThresholds` ([classify.hpp](include/damov/classify.hpp))
  *and* in [configs/damov.yaml](configs/damov.yaml), which the pipeline passes
  on the command line. Change both, or the CLI silently overrides the default.
- **gem5 stat names are version-dependent**, so `metrics.cpp` matches
  *substrings* via `StatPatterns`. Prefer adding a pattern over hard-coding a
  stat name; user overrides go through `damov-stats --patterns`
  ([configs/stat_patterns.example.ini](configs/stat_patterns.example.ini)
  mirrors the defaults and should be kept in sync).
- **`workloads/` and `out/` are gitignored** (see [.gitignore](.gitignore)).
  The instrumented STREAM example under `workloads/STREAM/` is therefore
  untracked local content even though the README describes it — don't assume a
  fresh clone has it.
- **HBM2 needs `channel_width=128`.** In `gem5/ramulator2/hmc.py` and
  `ramulator2_mem.py::_hbm2_memory_system`, the default 64-bit channel gives
  32-byte DRAM transactions while gem5 issues 64-byte requests, and Ramulator2
  errors out. Any new 3D-stacked preset must be verified to yield 64-byte
  transactions (drive it through `ramulator.frontend.SimpleO3` standalone first).
- **Classification reads the highest core count** for scalar AI/MPKI/LFMR and
  uses the whole sweep only for the LFMR trend — intentional, see
  docs/methodology.md. Note `ClassifyThresholds::lfmr` (0.56) is currently
  unused by `classify()`: the tree branches on the LFMR *trend*, not magnitude.
- **The library and CLI disagree on locality granularity on purpose.**
  `LocalityConfig::granularity` defaults to 1 (bytes); `damov-locality` sets 8
  (word) because that is the methodology's unit. Call sites that construct
  `LocalityAnalyzer` directly must set it themselves or sequential access scores
  0.125 instead of 1.0.
- Building gem5 needs system packages beyond the C++ toolchain, at minimum `m4`
  and `protobuf-compiler` (the latter for CommMonitor trace dumping). Pinned
  versions: gem5 v25.1, Ramulator2 v2.1.
- SLURM runs are driven by [slurm/](slurm/); `slurm/env.sh` is the single place
  to set cluster paths, and it exports the `DAMOV2_*` variables that
  `load_config` honours. gem5 is host-single-threaded — memory, not CPUs, is the
  constraint, and it scales with the number of *simulated* cores.
