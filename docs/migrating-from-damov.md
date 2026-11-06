# Migrating from the original DAMOV

This guide is for people who already run the original, ZSim-based DAMOV
([CMU-SAFARI/DAMOV](https://github.com/CMU-SAFARI/DAMOV), or the lab fork
[biopim/damov](https://github.com/biopim/damov)) with **command files** and
`generate_config_files.py`, and want to run the same functions on DAMOV2
(gem5 + Ramulator2).

DAMOV2 keeps the methodology, so your list of hot functions, inputs and
sweep carry over. What changes is everything around them: the simulator, how
a run is described, and how the ROI is marked. Converting the files is
mechanical, and [`scripts/migrate_damov.py`](../scripts/migrate_damov.py) does
it. Rebuilding the workloads is the one step you have to do by hand.

## TL;DR

```bash
# 1. Convert command files (+ the sweep in your generator) to DAMOV2 inputs.
scripts/migrate_damov.py ~/damov/simulator/command_files \
    --generator ~/damov/simulator/scripts/generate_config_files.py \
    --pim-root /path/to/damov/workloads        # omit to use ./workloads
#   -> benchmarks/damov/<benchmark>.yaml
#   -> configs/damov_migrated_ooo.yaml, configs/damov_migrated_inorder.yaml

# 2. Rebuild each workload for gem5 against the zsim-compat hooks (see §4).
cc ... -I$PWD/hooks/compat -I$PWD/hooks -I$GEM5/include -DDAMOV_USE_M5OPS \
       -L$GEM5/util/m5/build/x86/out -lm5

# 3. Run, locally or on SLURM.
scripts/damov2_pipeline.py --descriptor benchmarks/damov/stream.yaml \
    --config configs/damov_migrated_ooo.yaml
DAMOV2_CONFIG=configs/damov_migrated_ooo.yaml \
DAMOV2_DESCRIPTOR=$PWD/benchmarks/damov/stream.yaml DAMOV2_SUITE=stream \
    slurm/submit.sh
```

`benchmarks/damov/` and `configs/damov_migrated_*.yaml` are already in the
repository. They were converted from `biopim/damov@4d611a5`: all 17 command
files (151 functions in 16 suites, since `bwa_cf` and `bwamem_cf` both belong
to suite `bwa`) and the V2 generator's sweep. Re-run step 1 with `--force` if
your command files or generator differ.

## 1. Concept map

| Original DAMOV | DAMOV2 |
|----------------|--------|
| ZSim (Pin) + Ramulator v1 | gem5 SE mode + Ramulator2 |
| `simulator/command_files/<x>_cf` | `benchmarks/damov/<benchmark>.yaml` (descriptor) |
| `generate_config_files.py` → one ZSim `.cfg` + one `.slurm` per job | `generate_configs.py` → one `plan.json` per suite; `export_joblist.py` → one array-job line per job |
| `number_of_cores`, `platforms`, `versions` in the generator | `cores`, `configs`, `cpu_type` in `configs/*.yaml` |
| `templates/template_*.cfg` | [`gem5/configs/caches.py`](../gem5/configs/caches.py) + [`damov_se.py`](../gem5/configs/damov_se.py) |
| `ramulator-configs/HMC-config.cfg` | `ramulator_config: hmc` (preset) or a Ramulator2 DSL/YAML file |
| `workloads/zsim_hooks.h` | [`hooks/damov_hooks.h`](../hooks/damov_hooks.h), or the shim [`hooks/compat/zsim_hooks.h`](../hooks/compat/zsim_hooks.h) |
| `./build/opt/zsim <cfg>` | `scripts/run_experiment.py --plan ...` (or the pipeline) |
| `templates/template_slurm.slurm` | [`slurm/`](../slurm/) array job (`env.sh`, `submit.sh`) |
| `zsim_stats/<platform>/<cores>/<bench>_<app>_<fn>.zsim.out` | `out/<suite>/<app>_<fn>/<config>/<cores>/stats.txt` |
| `get_stats_per_app.py` (prints IPC/MPKI/LFMR) | `collect_stats.py` → CSV, then `damov-classify` → class + mitigation |
| Locality analysis: separate Python scripts | Step-2 trace job in every plan + `damov-locality` |
| Classification by hand from the metrics | `damov-classify` (paper Fig. 26 decision tree) |

## 2. Command files → descriptors

A DAMOV command-file line

```
ligra,BC,computeRmat,PIM_ROOT/ligra/apps/BC_Compute -t THREADS -s PIM_ROOT/ligra/inputs/rMat_20M
```

becomes this entry in `benchmarks/damov/ligra.yaml`:

```yaml
suite: "ligra"
functions:
  - name: "BC_computeRmat"    # ligra_cf:1, DAMOV stats ligra_BC_computeRmat
    binary: "{root}/workloads/ligra/apps/BC_Compute"
    options: "-t {threads} -s {root}/workloads/ligra/inputs/rMat_20M"
```

The rules `migrate_damov.py` applies:

- **Suite**: the first column (`benchmark`). Lines are grouped by it across all
  input files, so `bwa_cf` and `bwamem_cf` end up together in `bwa.yaml`.
- **Function name**: `<application>_<function>`, the same name DAMOV used in
  its config and stats filenames, so old and new results are easy to match.
  The trailing comment keeps the source `file:line` and the full DAMOV stats
  id. Characters other than `[A-Za-z0-9_.+-]` become `_` because the name is
  used as a directory. A duplicate name within a suite gets a `_2` suffix and
  a warning (DAMOV would silently have overwritten the first one's configs).
- **`binary` / `options`**: the first word of the command, then the rest.
  gem5 splits `options` on whitespace and does not use a shell, which is also
  how ZSim treated the command.
- **`PIM_ROOT`** (DAMOV's `<repo>/workloads/`) becomes `--pim-root`. The
  default is `{root}/workloads`, i.e. this repository's (gitignored)
  `workloads/` directory, which is where `benchmarks/get_workloads.sh` puts
  the sources. To reuse an existing DAMOV checkout, pass its absolute path:
  `--pim-root ~/damov/workloads`.
- **`THREADS`** becomes `{threads}`. Both placeholders are DAMOV2 descriptor
  features that `generate_configs.py` expands for each job:

  | Placeholder | Expands to |
  |-------------|------------|
  | `{threads}` | the job's simulated core count; `1` for the Step-2 trace job |
  | `{root}`    | the absolute DAMOV2 repository root |

  As in DAMOV, the substitution is plain text, so it also works inside paths
  (`run_..._{threads}_core.sh`) and glued to flags (`-p{threads}`).
- **`< file`** becomes the descriptor's `input:` field (stdin). Other shell
  operators (`>`, `|`, ...) are kept as literal arguments, with a warning.
- **`class:`**, the expected class that DAMOV2 descriptors may carry for
  validation, is not part of DAMOV command files. Add it by hand if you know
  it from the paper's tables.

Every descriptor is parsed back with both YAML loaders the pipeline may use
(PyYAML and the built-in fallback) before it is written, so a conversion that
would load differently fails instead.

### Things the converter flags

- **Shell-script commands** (`splash2_cf`'s Barnes entries run
  `run_splash2_barnes_*_THREADS_core.sh`): gem5 SE mode cannot execute a
  script. Edit `binary`/`options` to the program the script launches.
- **Functions without `THREADS`** (22 of the 151 in biopim/damov, e.g. the
  PolyBench and HPCC binaries): DAMOV2 runs them as they are. They pick their
  own thread count, typically OpenMP's default from the number of CPUs the
  simulated system reports. Check that this is what you expect for every core
  count.
- **Suite name collisions**: migrated suites write to `out/<suite>/`. The
  migrated `stream` suite shares that directory, and so `plan.json`, with the
  native [`benchmarks/stream.yaml`](../benchmarks/stream.yaml). Use a separate
  `output_root` (or `DAMOV2_OUTPUT_ROOT`) if you run both.

## 3. `generate_config_files.py` → DAMOV2 configs

DAMOV's generator wrote one ZSim config and one SLURM script per
(function × platform × version × core count). DAMOV2 instead keeps the sweep
in one config file and expands it at plan time. Pass your generator with
`--generator`. The script **parses it with `ast` and does not execute it**,
reading three literal lists from it:

| Generator (biopim/damov V2) | DAMOV2 config key | Mapping |
|-----------------------------|-------------------|---------|
| `number_of_cores = [1, 4, 16, 20, 32, 40, 64, 80, 112, 128, 256]` | `cores` | copied |
| `platforms`: `host_{0}/no_prefetch` | `configs` | `host_ooo` |
| `platforms`: `host_{0}/prefetch` | `configs` | `host_prefetch` |
| `platforms`: `pim_{0}` | `configs` | `ndp` |
| `versions`: `ooo` | `cpu_type` | `O3` → `configs/damov_migrated_ooo.yaml`, `output_root: out` |
| `versions`: `inorder` | `cpu_type` | `Timing` → `configs/damov_migrated_inorder.yaml`, `output_root: out-inorder` |
| `versions`: `accelerator` | — | **skipped**: ZSim's accelerator core model has no gem5 counterpart |

`cpu_type` is a global setting in DAMOV2, so each core version gets its own
config file and output root, and the O3 and in-order sweeps never overwrite
each other. Everything else in the generated config (paths, memory model,
thresholds) is copied verbatim from `configs/damov.yaml`. V1 of the generator
defines only `number_of_cores`, so with V1 the configs default to all three
platforms and version `ooo`.

The sweep counts as one job per entry, plus one trace job per function. With
V2's 11 core counts × 3 platforms, the 151 migrated functions come to
151 × (1 + 33) = **5,134 gem5 jobs per core version**.

**Host memory.** gem5 needs much more host RAM per simulated core than ZSim.
A 256-core O3 run needs about 60 GB (see the
[core-count note](../README.md#the-core-count-sweep-and-the-256-core-point)),
and the 80–128-core points are also large. Either set `SLURM_MEM` generously
for these runs or trim `cores` in the migrated config. Classification reads the
highest core count for its scalar metrics, so a sweep whose top point failed
misclassifies.

### Templates (`template_*.cfg`)

DAMOV2 builds the systems in code instead of filling in templates. The paper's
Table 1 values, which DAMOV's templates also use, are built in:

| DAMOV template | DAMOV2 | Where |
|----------------|--------|-------|
| `template_host_{ooo,inorder}.cfg`: L1 32 KB, L2 256 KB, L3 8 MB / 16 banks, 2.4 GHz | `host_ooo` | `caches.py`, `damov_se.py --freq` |
| `template_host_prefetch_*.cfg`: + `l2prefetcher` | `host_prefetch` (stride prefetcher on L2) | `caches.py` |
| `template_pim_*.cfg`: L1 only, L3 bypassed, 4 banks | `ndp`: private L1 only, no L2/L3 | `caches.py` |
| `template_host_nuca*.cfg` | — | not ported |
| `mem.type = "Ramulator"`, `HMC-config.cfg` | `ramulator_config: hmc` (3D-stacked HBM2 model) | `ramulator2_mem.py` |
| `sim.maxTotalInstrs` | `damov_se.py --max-insts N` | not yet set through the plan |
| `sim.gmMBytes = 8192` | `damov_se.py --mem-size 8GB` | |
| `pinOptions`, `phaseLength`, `startFastForwarded` | — | ZSim-specific. DAMOV2 fast-forwards on a TimingSimple CPU up to `damov_roi_begin()` |

If you edited a template (cache sizes, latencies), make the same change in
`gem5/configs/caches.py`. If you used a different Ramulator config, point
`ramulator_config` at a Ramulator2 DSL/YAML file. Ramulator v1 `.cfg` files
are **not** compatible, and 3D-stacked presets have to yield 64-byte
transactions (see `CLAUDE.md`, "HBM2 needs `channel_width=128`").

## 4. ROI hooks: rebuilding the workloads

Binaries built for DAMOV **cannot be reused**. ZSim's magic op is
`xchg %rcx, %rcx`, which gem5 executes as an ordinary NOP. The ROI is never
seen, the detailed CPU never switches in, and the "results" describe the
warm-up CPU running the whole program. Every workload must be recompiled.

Rebuilding does not require editing the sources. `hooks/compat/zsim_hooks.h`
implements DAMOV's hook API on top of `damov_hooks.h`:

| DAMOV (`zsim_hooks.h`) | DAMOV2 (`damov_hooks.h`) |
|------------------------|--------------------------|
| `zsim_roi_begin()` / `zsim_roi_end()` | `damov_roi_begin()` / `damov_roi_end()` |
| `zsim_PIM_function_begin()` / `zsim_PIM_function_end()` | `damov_function_begin()` / `damov_function_end()` |
| `zsim_begin()` / `zsim_end()` | both pairs, in DAMOV's order |
| `zsim_heartbeat()`, `zsim_work_begin/end()` | no-ops |

Put the compat directory **first** on the include path and select a backend
as usual:

```bash
# gem5 build (libm5)
CFLAGS+=" -I<damov2>/hooks/compat -I<damov2>/hooks -I<gem5>/include -DDAMOV_USE_M5OPS"
LDFLAGS+=" -L<gem5>/util/m5/build/x86/out -lm5"
# gem5 build without libm5:  -DDAMOV_USE_MAGIC instead of the two lines above
# native build for Step-1 VTune profiling: just -I<damov2>/hooks/compat -I<damov2>/hooks
```

Watch out for **private copies**. Many DAMOV workloads carry their own
`zsim_hooks.h` next to the sources. `#include "zsim_hooks.h"` searches the
source directory before any `-I` path, so that copy wins over the shim.
Delete it or overwrite it with `hooks/compat/zsim_hooks.h`. To find the copies:

```bash
find workloads -name zsim_hooks.h
```

Calls to `zsim_magic_op()` itself have no DAMOV2 equivalent. Replace them with
the hook they implement. Once a workload is ported for good, it is cleaner to
switch it to `#include "damov_hooks.h"` and the `damov_*` names.

## 5. Running

| DAMOV | DAMOV2 |
|-------|--------|
| `python scripts/generate_config_files.py command_files/stream_cf` | `scripts/generate_configs.py --descriptor benchmarks/damov/stream.yaml --config configs/damov_migrated_ooo.yaml` |
| `./build/opt/zsim config_files/host_ooo/no_prefetch/stream/4/Add_Add.cfg` | `scripts/run_experiment.py --plan out/stream/plan.json --function Add_Add --configs host_ooo --cores 4` |
| `./build/opt/zsim config_files/pim_ooo/stream/4/Add_Add.cfg` | same with `--configs ndp` |
| (none: locality was a separate flow) | `scripts/run_experiment.py --plan out/stream/plan.json --stage trace` |
| `python scripts/get_stats_per_app.py zsim_stats/.../stream_Add_Add.zsim.out` | `scripts/collect_stats.py --suite stream --function Add_Add` |
| (manual) | `build/damov-classify --metrics out/stream/Add_Add.metrics.csv --locality out/stream/Add_Add.locality.csv --pretty` |
| all of the above | `scripts/damov2_pipeline.py --descriptor benchmarks/damov/stream.yaml --config configs/damov_migrated_ooo.yaml` |

Add `--dry-run` to `run_experiment.py` or the pipeline to print the gem5
command lines without running them.

### SLURM

DAMOV's template wrote one `.slurm` per job (`-p hi_end -w lisa -c THREADS`).
DAMOV2 submits a single array job covering the whole plan, followed by a
dependent analysis job:

| `template_slurm.slurm` | DAMOV2 (`slurm/env.sh` or the environment) |
|------------------------|--------------------------------------------|
| `-p hi_end` | `SLURM_PARTITION=hi_end` |
| `-w lisa` | `SLURM_EXTRA_ARGS="-w lisa"` |
| `-c THREADS` (≤ 64) | `SLURM_CPUS=2`: gem5 is single-threaded on the host, so simulated cores need host **memory**, not CPUs (`SLURM_MEM`) |
| one job per cfg | `SLURM_MAX_PARALLEL` throttles the array |
| `slurmout/JOBNAME.%j.out` | `damov2-sim-<array>_<task>.out` in the submit directory |
| which sweep | `DAMOV2_CONFIG=configs/damov_migrated_ooo.yaml` |
| which command file | `DAMOV2_DESCRIPTOR=<abs path>/benchmarks/damov/<suite>.yaml DAMOV2_SUITE=<suite>` |

```bash
DAMOV2_CONFIG=configs/damov_migrated_ooo.yaml \
DAMOV2_DESCRIPTOR=$PWD/benchmarks/damov/ligra.yaml DAMOV2_SUITE=ligra \
SLURM_PARTITION=hi_end SLURM_EXTRA_ARGS="-w lisa" SLURM_MEM=64G \
    slurm/submit.sh
```

## 6. What does not carry over

- **Numbers.** gem5's O3 core, its classic caches and Ramulator2 are not ZSim
  and Ramulator v1. Expect IPC, MPKI and LFMR to differ from DAMOV runs. Class
  assignments should mostly agree, since the methodology and thresholds are
  the same, but re-validate rather than mixing old and new results.
- **The `accelerator` core version** and the **NUCA templates** are not ported.
- **Shell-script workloads** need their real binary (see §2).
- **ZSim stats layout.** Scripts that parse `*.zsim.out` / `*.zsim-ev.h5` need
  to switch to `collect_stats.py`'s CSV output (`out/<suite>/<fn>.metrics.csv`).
- **Input sizes** come from the command files unchanged, and some are slow to
  simulate on gem5. Shrink them in the descriptor's `options` if needed, as
  `benchmarks/stream.yaml` does.

## Reference: `migrate_damov.py` options

| Option | Default | Meaning |
|--------|---------|---------|
| positional | — | command file(s) and/or `command_files/` directories (`*.bak`, `*~` and dotfiles skipped) |
| `--generator PATH` | — | DAMOV `generate_config_files.py` whose sweep to migrate; without it no config is written |
| `--out-dir DIR` | `benchmarks/damov` | descriptor output directory |
| `--pim-root STR` | `{root}/workloads` | replacement for `PIM_ROOT` |
| `--config-template PATH` | `configs/damov.yaml` | base for migrated configs |
| `--config-prefix PATH` | `configs/damov_migrated` | configs are `<prefix>_<version>.yaml` |
| `--upstream STR` | — | provenance note written into file headers (e.g. `biopim/damov@4d611a5`) |
| `--force` | off | overwrite existing outputs |
| `--dry-run` | off | print everything, write nothing |
