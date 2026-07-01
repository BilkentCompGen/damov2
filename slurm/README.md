# Running DAMOV2 on a SLURM cluster

These scripts run the full characterization of a benchmark descriptor as a SLURM
array job (one gem5 + Ramulator2 simulation per array task), followed by a
dependent analysis job that classifies each function.

```
slurm/
├── env.sh              # EDIT THIS: paths + resource defaults (sourced by all)
├── 00_prepare.sh       # build tools+workload, generate plan + joblist  (login node)
├── 10_simulate.sbatch  # SLURM array: one gem5 sim per task
├── 20_analyze.sbatch   # dependent: collect stats + classify (writes summary CSV)
└── submit.sh           # does 00 + submits 10 and 20 with the right dependency
```

## 1. Configure

Edit [`env.sh`](env.sh) (or export the variables before submitting):

| Variable | Meaning |
|----------|---------|
| `GEM5_ROOT` / `DAMOV2_GEM5_BIN` | your gem5 checkout / the `gem5.opt` binary |
| `DAMOV2_RAMULATOR_CONFIG` | Ramulator2 memory YAML (default: HMC-config.yaml) |
| `DAMOV2_CPU_TYPE` | `O3` (out-of-order) or `Timing` (in-order) |
| `DAMOV2_DESCRIPTOR` / `DAMOV2_SUITE` | which benchmark descriptor to run |
| `SLURM_PARTITION`, `SLURM_ACCOUNT`, `SLURM_TIME`, `SLURM_MEM`, `SLURM_CPUS` | job resources |
| `SLURM_MAX_PARALLEL` | array throttle (`%N` — max concurrent tasks) |

Prerequisite: gem5 built with the Ramulator2 memory model (see
[../gem5/README.md](../gem5/README.md)).

## 2. Submit everything

```bash
slurm/submit.sh
```

This builds the DAMOV2 tools + instrumented STREAM, generates the run plan and
joblist, submits the simulation array, and submits the analysis job with an
`afterok` dependency on the array. Results land in
`out/<suite>/<suite>.classification.csv`.

Override resources per run without editing `env.sh`:

```bash
SLURM_MEM=64G SLURM_TIME=48:00:00 SLURM_PARTITION=bigmem slurm/submit.sh
```

## 3. Or run the stages manually

```bash
source slurm/env.sh
bash slurm/00_prepare.sh                       # -> out/stream/{plan.json,joblist.txt}

N=$(wc -l < out/stream/joblist.txt)
sbatch --array=0-$((N-1))%32 --mem=16G --time=24:00:00 \
       --export=ALL,DAMOV2_ROOT="$DAMOV2_ROOT",JOBLIST="$PWD/out/stream/joblist.txt" \
       slurm/10_simulate.sbatch

# after the array finishes:
sbatch --export=ALL,DAMOV2_ROOT="$DAMOV2_ROOT" slurm/20_analyze.sbatch
```

## Resource sizing note

gem5 SE simulation is **host-single-threaded**; host RAM (not CPUs) is the
constraint, and it grows with the number of *simulated* cores. A 256-core O3 run
can need tens of GB, while a 1-core run needs ~1–2 GB. The array uses uniform
resources, so either:

- set `SLURM_MEM` to satisfy the largest (256-core) task, or
- submit the low- and high-core-count jobs as separate arrays with different
  `--mem`, filtering the joblist by core count, e.g.:

  ```bash
  grep -- '--cores 256' out/stream/joblist.txt > out/stream/joblist.256.txt
  ```

## Retrying failed tasks

Array tasks are independent. Re-run only the failures by passing their indices:

```bash
sbatch --array=7,19,42 --mem=64G \
       --export=ALL,DAMOV2_ROOT="$DAMOV2_ROOT",JOBLIST="$PWD/out/stream/joblist.txt" \
       slurm/10_simulate.sbatch
```
