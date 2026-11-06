# DAMOV2 SLURM environment — EDIT THIS for your cluster, then it is sourced by
# every slurm/*.sh script. Nothing here submits jobs; it only sets paths and
# resource defaults.

# --- Repo & tool locations -------------------------------------------------
# Auto-detect the repo root (this file lives in <root>/slurm/).
export DAMOV2_ROOT="${DAMOV2_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export PYTHON="${PYTHON:-python3}"

# DAMOV2 C++ tools (built by 00_prepare.sh into $DAMOV2_ROOT/build).
export DAMOV2_TOOLS_DIR="${DAMOV2_TOOLS_DIR:-$DAMOV2_ROOT/build}"

# --- Simulators (git submodules under external/) ---------------------------
# gem5 built with the Ramulator2 wrapper — see gem5/README.md, or run
# scripts/setup_gem5_ramulator2.sh once to build+wire both submodules.
export GEM5_ROOT="${GEM5_ROOT:-$DAMOV2_ROOT/external/gem5}"
export DAMOV2_GEM5_BIN="${DAMOV2_GEM5_BIN:-$GEM5_ROOT/build/X86/gem5.opt}"
export DAMOV2_GEM5_CONFIG="${DAMOV2_GEM5_CONFIG:-$DAMOV2_ROOT/gem5/configs/damov_se.py}"

# Ramulator2 checkout + memory model. DAMOV2_RAMULATOR_CONFIG is a preset name
# (hmc / hbm2 / ddr4) or a path to a Ramulator2 DSL/YAML/JSON config.
export RAMULATOR2_HOME="${RAMULATOR2_HOME:-$DAMOV2_ROOT/external/ramulator2}"
export DAMOV2_RAMULATOR_HOME="${DAMOV2_RAMULATOR_HOME:-$RAMULATOR2_HOME}"
export DAMOV2_RAMULATOR_CONFIG="${DAMOV2_RAMULATOR_CONFIG:-hmc}"
# Ramulator2's shared lib + Python DSL must be discoverable at run time.
export LD_LIBRARY_PATH="$RAMULATOR2_HOME:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$RAMULATOR2_HOME/python:${PYTHONPATH:-}"

# Core model for the sweep: O3 (out-of-order) or Timing (in-order).
export DAMOV2_CPU_TYPE="${DAMOV2_CPU_TYPE:-O3}"

# Where gem5 outputs and metric tables are written.
export DAMOV2_OUTPUT_ROOT="${DAMOV2_OUTPUT_ROOT:-$DAMOV2_ROOT/out}"

# Global config file (core sweep, configs, thresholds). Unset = configs/damov.yaml.
# Point it at a migrated config, e.g. configs/damov_migrated_ooo.yaml, to run
# the sweep of an original-DAMOV generate_config_files.py
# (docs/migrating-from-damov.md).
export DAMOV2_CONFIG="${DAMOV2_CONFIG:-}"

# --- Which benchmark descriptor to characterize ----------------------------
export DAMOV2_DESCRIPTOR="${DAMOV2_DESCRIPTOR:-$DAMOV2_ROOT/benchmarks/stream.yaml}"
export DAMOV2_SUITE="${DAMOV2_SUITE:-stream}"

# --- SLURM resource defaults (override on the sbatch/submit command line) ---
# gem5 SE simulation is host-single-threaded; memory grows with the number of
# SIMULATED cores (a 256-core run needs far more host RAM than a 1-core run).
export SLURM_PARTITION="${SLURM_PARTITION:-cpu}"
export SLURM_ACCOUNT="${SLURM_ACCOUNT:-}"          # set if your site requires it
export SLURM_TIME="${SLURM_TIME:-24:00:00}"
export SLURM_MEM="${SLURM_MEM:-16G}"               # per array task; raise for 256-core
export SLURM_CPUS="${SLURM_CPUS:-2}"               # host cores per gem5 process
export SLURM_MAX_PARALLEL="${SLURM_MAX_PARALLEL:-32}"  # array throttle (%N)
# Extra sbatch flags for both submissions, word-split, e.g. "-w lisa" to pin a
# node as DAMOV's template_slurm.slurm did.
export SLURM_EXTRA_ARGS="${SLURM_EXTRA_ARGS:-}"

# Optional environment modules — uncomment/edit for your site.
# module load gcc/12 cmake/3.27 python/3.11 2>/dev/null || true
