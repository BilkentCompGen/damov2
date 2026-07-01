#!/usr/bin/env bash
# Step 0 (login node): build the DAMOV2 tools + workload, generate the run plan,
# and export the SLURM joblist. Fast and non-parallel; safe to run on a login
# node. Produces:
#   $DAMOV2_OUTPUT_ROOT/<suite>/plan.json
#   $DAMOV2_OUTPUT_ROOT/<suite>/joblist.txt      (one gem5 command per line)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

cd "$DAMOV2_ROOT"

echo "==> Building DAMOV2 C++ tools"
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build build -j >/dev/null
echo "    tools in $DAMOV2_TOOLS_DIR"

echo "==> Building instrumented workload(s)"
if [[ -f workloads/STREAM/Makefile ]]; then
    make -C workloads/STREAM GEM5_ROOT="$GEM5_ROOT" gem5 \
        || echo "    WARNING: STREAM gem5 build failed (check GEM5_ROOT/libm5)"
fi

echo "==> Generating run plan from $DAMOV2_DESCRIPTOR"
$PYTHON scripts/generate_configs.py --descriptor "$DAMOV2_DESCRIPTOR"

PLAN="$DAMOV2_OUTPUT_ROOT/$DAMOV2_SUITE/plan.json"
JOBLIST="$DAMOV2_OUTPUT_ROOT/$DAMOV2_SUITE/joblist.txt"

echo "==> Exporting SLURM joblist"
$PYTHON scripts/export_joblist.py --plan "$PLAN" --out "$JOBLIST"

N=$(wc -l < "$JOBLIST")
echo
echo "Prepared $N jobs."
echo "  plan    : $PLAN"
echo "  joblist : $JOBLIST"
echo "Next: slurm/submit.sh   (or sbatch slurm/10_simulate.sbatch manually)"
