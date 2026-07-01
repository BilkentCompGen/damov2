# DAMOV2 — gem5 + Ramulator2 integration

DAMOV2 replaces the original DAMOV-SIM (ZSim + Ramulator v1) with **gem5** driving
**Ramulator2** as its main-memory model. Both simulators are vendored as git
**submodules** so versions are pinned:

| Submodule | Path | Upstream |
|-----------|------|----------|
| gem5       | `external/gem5`       | https://github.com/gem5/gem5.git |
| Ramulator2 | `external/ramulator2` | https://github.com/CMU-SAFARI/ramulator2.git |

## 0. Get the submodules

If you cloned DAMOV2 without `--recursive`:

```bash
git submodule update --init --depth 1 external/ramulator2 external/gem5
```

## 1. Automated setup (recommended)

```bash
scripts/setup_gem5_ramulator2.sh X86 $(nproc)
```

This runs the four steps below for you: builds Ramulator2, installs its gem5
wrapper into `external/gem5/src/mem/ramulator2/`, points the wrapper's SConscript
at `external/ramulator2`, and builds `external/gem5/build/X86/gem5.opt`. Skip to
§3 afterwards.

## 2. Manual setup (what the script does)

Ramulator2 v2.1 ships its own gem5 wrapper (an `AbstractMemory` SimObject named
`Ramulator2`) under `resources/gem5_wrappers/`. Integration is:

```bash
# a) Build Ramulator2 -> libramulator.so
cmake -S external/ramulator2 -B external/ramulator2/build -DCMAKE_BUILD_TYPE=Release
cmake --build external/ramulator2/build -j

# b) Install the wrapper into gem5's source tree
cp external/ramulator2/resources/gem5_wrappers/{ramulator2.hh,ramulator2.cc,Ramulator2.py,SConscript} \
   external/gem5/src/mem/ramulator2/

# c) Point the wrapper at your Ramulator2 checkout
#    edit external/gem5/src/mem/ramulator2/SConscript:
#      RAMULATOR2_HOME = '<abs path>/external/ramulator2'

# d) Build gem5
cd external/gem5 && scons build/X86/gem5.opt -j$(nproc) --ignore-style
```

The wrapper's `SConscript` sets `RPATH` so `libramulator.so` is found at run
time. If you relocate the library, `export LD_LIBRARY_PATH=<ramulator2>`.

Tested with **gem5 v25.1** and **Ramulator2 v2.1** (per Ramulator2's README §6).

## 3. How DAMOV2 configures the memory

The `Ramulator2` SimObject takes one string parameter, `ramulator_config` — a
JSON document describing the memory system. DAMOV2 builds that string from
Ramulator2's **Python DSL** (`external/ramulator2/python`) via
[`configs/ramulator2_mem.py`](configs/ramulator2_mem.py), selecting a model by
name or from a DSL file:

| `--ramulator-config` value | Memory modeled |
|----------------------------|----------------|
| `hmc` / `hbm2`             | 3D-stacked HBM2 (HMC-equivalent, Table 1) — [`ramulator2/hmc.py`](ramulator2/hmc.py) |
| `ddr4`                     | commodity off-chip DDR4 — [`ramulator2/ddr4.py`](ramulator2/ddr4.py) |
| a path to `*.py`          | a custom Ramulator2 DSL script exposing a `mem` object |
| a path to `*.yaml`/`*.json`| a Ramulator2 config used verbatim |

Ramulator2 has no HMC standard, so the paper's Hybrid Memory Cube is modeled with
HBM2 (its pseudochannel/bankgroup/bank levels provide the vault/bank parallelism).
Preview the generated config with:

```bash
python gem5/configs/ramulator2_mem.py hmc | head
```

## 4. Configuration scripts

| File | Purpose |
|------|---------|
| `configs/damov_se.py`     | SE-mode driver: host_ooo / host_prefetch / ndp systems, ROI CPU switching, optional memory-trace dump, Ramulator2 memory. |
| `configs/caches.py`       | Cache hierarchy classes matching Table 1 (L1/L2/L3, prefetcher, NDP L1). |
| `configs/ramulator2_mem.py` | Builds the `ramulator_config` string from the Ramulator2 Python DSL. |
| `ramulator2/hmc.py`       | 3D-stacked (HBM2) memory DSL config. |
| `ramulator2/ddr4.py`      | Commodity DDR4 DSL config. |

## 5. Running one simulation

```bash
external/gem5/build/X86/gem5.opt --outdir=out/stream_Add/host_ooo/4 \
    gem5/configs/damov_se.py \
    --config host_ooo --cores 4 --cpu-type O3 \
    --ramulator-config hmc --ramulator-home external/ramulator2 \
    --cmd workloads/STREAM/stream_omp --options "add 8000000"
```

Outputs land in the `--outdir`: gem5's `stats.txt` and Ramulator2's
`ramulator_stats.yaml`. Feed both to `damov-stats` (the orchestration scripts do
this automatically). Add `--debug-flags=Ramulator2` for request-level tracing.

## 6. Region-of-interest (ROI) protocol

Workloads are annotated with [`../hooks/damov_hooks.h`](../hooks/damov_hooks.h).
`damov_roi_begin()` emits an `m5_work_begin`; `damov_se.py` runs an AtomicSimple
CPU for warm-up and switches to the detailed O3/Timing CPU + Ramulator2 at the
ROI, then resets stats. `damov_function_begin/end()` bracket each offloadable
function so the dumped stats measure that function only — the granularity DAMOV
classifies at.

## Three system configurations (Table 1)

- **host_ooo** — 4-wide OoO cores; private L1 (32 KB) + L2 (256 KB); shared L3
  (8 MB, 16 banks); no prefetcher.
- **host_prefetch** — host_ooo + a 2-degree stride prefetcher on L2.
- **ndp** — cores in the memory logic layer; a single private read-only L1
  (32 KB), no L2/L3, no prefetcher; direct access to Ramulator2 DRAM.

Core counts: 1, 4, 16, 64, 256. Core model: `--cpu-type O3` or `--cpu-type Timing`.
