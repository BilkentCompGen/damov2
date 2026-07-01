#!/usr/bin/env bash
#SBATCH --job-name=damov2-sim
#SBATCH --output=%x-%A_%a.out
#SBATCH --error=%x-%A_%a.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
# Resources (partition/time/mem/cpus) are supplied by submit.sh from env.sh, or
# override on the sbatch command line. The array range is set by submit.sh to
# match the joblist length.
#
# Each array task runs ONE gem5 + Ramulator2 simulation: the (TASK_ID+1)-th line
# of the joblist. Standalone use:
#   JOBLIST=out/stream/joblist.txt sbatch --array=0-63 slurm/10_simulate.sbatch
set -euo pipefail
# submit.sh exports DAMOV2_ROOT and JOBLIST into the job environment.
source "${DAMOV2_ROOT:?set DAMOV2_ROOT (or submit via slurm/submit.sh)}/slurm/env.sh"

: "${JOBLIST:?JOBLIST must point to the exported joblist.txt}"

LINE=$(( SLURM_ARRAY_TASK_ID + 1 ))
CMD=$(sed -n "${LINE}p" "$JOBLIST")
if [[ -z "$CMD" ]]; then
    echo "no job at line $LINE of $JOBLIST" >&2
    exit 1
fi

echo "[task $SLURM_ARRAY_TASK_ID] host=$(hostname) $(date)"
echo "  $CMD"

# Respect the SLURM cpu allocation for any host-side threading gem5 may use.
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"

eval "$CMD"
echo "[task $SLURM_ARRAY_TASK_ID] done $(date)"
