#!/usr/bin/env bash
# One-shot DAMOV2 cluster submission:
#   1. prepare (build tools+workload, generate plan+joblist)   [login node]
#   2. submit the gem5 simulation array                        [SLURM]
#   3. submit the analysis+classification job, dependent on (2) [SLURM]
#
# Usage:
#   slurm/submit.sh                          # uses env.sh defaults
#   SLURM_MEM=64G SLURM_TIME=48:00:00 slurm/submit.sh
#   slurm/submit.sh --skip-prepare           # reuse an existing plan/joblist
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

SKIP_PREPARE=0
[[ "${1:-}" == "--skip-prepare" ]] && SKIP_PREPARE=1

PLAN="$DAMOV2_OUTPUT_ROOT/$DAMOV2_SUITE/plan.json"
JOBLIST="$DAMOV2_OUTPUT_ROOT/$DAMOV2_SUITE/joblist.txt"

if [[ $SKIP_PREPARE -eq 0 ]]; then
    bash "$DAMOV2_ROOT/slurm/00_prepare.sh"
fi

[[ -s "$JOBLIST" ]] || { echo "joblist missing/empty: $JOBLIST" >&2; exit 1; }
N=$(wc -l < "$JOBLIST")
LAST=$(( N - 1 ))

SBATCH_OPT=()
[[ -n "$SLURM_ACCOUNT" ]] && SBATCH_OPT=(--account="$SLURM_ACCOUNT")
read -r -a EXTRA_OPT <<< "$SLURM_EXTRA_ARGS"
SBATCH_OPT+=("${EXTRA_OPT[@]}")

echo "==> Submitting simulation array (0-$LAST, throttle %$SLURM_MAX_PARALLEL)"
SIM_JID=$(sbatch --parsable \
    --partition="$SLURM_PARTITION" "${SBATCH_OPT[@]}" \
    --time="$SLURM_TIME" --mem="$SLURM_MEM" --cpus-per-task="$SLURM_CPUS" \
    --array="0-${LAST}%${SLURM_MAX_PARALLEL}" \
    --export=ALL,DAMOV2_ROOT="$DAMOV2_ROOT",JOBLIST="$JOBLIST" \
    "$DAMOV2_ROOT/slurm/10_simulate.sbatch")
echo "    array job id: $SIM_JID"

echo "==> Submitting analysis job (afterok:$SIM_JID)"
ANA_JID=$(sbatch --parsable \
    --partition="$SLURM_PARTITION" "${SBATCH_OPT[@]}" \
    --time="02:00:00" --mem="8G" \
    --dependency="afterok:${SIM_JID}" \
    --export=ALL,DAMOV2_ROOT="$DAMOV2_ROOT" \
    "$DAMOV2_ROOT/slurm/20_analyze.sbatch")
echo "    analysis job id: $ANA_JID"

echo
echo "Submitted. Monitor with:  squeue -u \$USER"
echo "Results will appear in:   $DAMOV2_OUTPUT_ROOT/$DAMOV2_SUITE/${DAMOV2_SUITE}.classification.csv"
