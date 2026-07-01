# DAMOV2 — gem5 + Ramulator2 integration

DAMOV2 replaces the original DAMOV-SIM (ZSim + Ramulator v1) with **gem5**
driving **Ramulator2** as its main-memory model. This directory holds the gem5
configuration scripts and the Ramulator2 memory configs; gem5 and Ramulator2
themselves are external and must be built once.

## 1. Build Ramulator2

```bash
git clone https://github.com/CMU-SAFARI/ramulator2.git
cd ramulator2 && mkdir build && cd build
cmake .. && make -j
```

## 2. Build gem5 with the Ramulator2 memory model

gem5 integrates Ramulator2 through the `ext/ramulator2` interface, exposing a
`Ramulator2` memory controller `SimObject`. Point gem5 at your Ramulator2 build
and compile:

```bash
git clone https://github.com/gem5/gem5.git
cd gem5
# Enable the Ramulator2 ext (link against the ramulator2 you built in step 1):
scons EXTRAS=ext/ramulator2 RAMULATOR2_DIR=/path/to/ramulator2 \
      build/X86/gem5.opt -j$(nproc)
```

If your gem5 tree does not yet vendor `ext/ramulator2`, copy the connector from
the Ramulator2 repo's `gem5_integration/` directory (it provides
`Ramulator2.py`, `Ramulator2.cc/.hh`, and the SConscript) into
`gem5/src/mem/ramulator2/` and add it to the build. The DAMOV2 config script
(`configs/damov_se.py`) only requires that `from m5.objects import Ramulator2`
succeeds and that the object exposes `config_path`, `range`, and `port`.

## 3. Configuration scripts

| File                     | Purpose                                                        |
|--------------------------|----------------------------------------------------------------|
| `configs/damov_se.py`    | SE-mode driver: builds host_ooo / host_prefetch / ndp systems, ROI CPU switching, optional memory-trace dump. |
| `configs/caches.py`      | Cache hierarchy classes matching Table 1 (L1/L2/L3, prefetcher, NDP L1). |
| `ramulator2/HMC-config.yaml` | 3D-stacked (HBM2-modeled HMC) main memory. |
| `ramulator2/DDR4-config.yaml`| Commodity off-chip DDR4 baseline. |

## 4. The three system configurations (Table 1)

- **host_ooo** — 4-wide OoO cores; private L1 (32 KB) + L2 (256 KB); shared L3
  (8 MB, 16 banks); no prefetcher.
- **host_prefetch** — host_ooo + a 2-degree stride prefetcher on L2.
- **ndp** — cores in the memory logic layer; a single private read-only L1
  (32 KB), no L2/L3, no prefetcher; direct access to Ramulator2 DRAM.

Core counts swept: 1, 4, 16, 64, 256. Core model: `--cpu-type O3` (out-of-order)
or `--cpu-type Timing` (in-order), per Section 3.5.2.

## 5. Running one simulation

```bash
build/X86/gem5.opt --outdir=out/stream_Add/host_ooo/4 \
    /path/to/damov2/gem5/configs/damov_se.py \
    --config host_ooo --cores 4 --cpu-type O3 \
    --ramulator-config /path/to/damov2/gem5/ramulator2/HMC-config.yaml \
    --cmd workloads/STREAM/stream_omp --options ""
```

Statistics land in `out/stream_Add/host_ooo/4/stats.txt` (gem5) and the
Ramulator2 stats file; feed both to `damov-stats`.

## 6. Region-of-interest (ROI) protocol

Workloads are annotated with `hooks/damov_hooks.h`. `damov_roi_begin()` emits an
`m5_work_begin`; `damov_se.py` runs an AtomicSimple CPU for warm-up and switches
to the detailed O3/Timing CPU + Ramulator2 exactly at the ROI, then resets
stats. `damov_function_begin/end()` bracket each offloadable function so the
dumped stats measure that function only — the granularity DAMOV classifies at.
