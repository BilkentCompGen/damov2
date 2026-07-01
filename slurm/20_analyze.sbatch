#!/usr/bin/env bash
#SBATCH --job-name=damov2-analyze
#SBATCH --output=%x-%j.out
#SBATCH --error=%x-%j.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
# Runs AFTER the simulation array completes (submit.sh wires the dependency).
# Collects gem5/Ramulator2 stats + locality per function and classifies each
# into its DAMOV bottleneck class. Writes a suite-wide summary CSV.
set -euo pipefail
source "${DAMOV2_ROOT:?set DAMOV2_ROOT (or submit via slurm/submit.sh)}/slurm/env.sh"

cd "$DAMOV2_ROOT"
SUITE="$DAMOV2_SUITE"
OUT="$DAMOV2_OUTPUT_ROOT/$SUITE"
SUMMARY="$OUT/${SUITE}.classification.csv"

# Discover the functions from the plan.
mapfile -t FUNCS < <($PYTHON - "$OUT/plan.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
seen = []
for j in plan["jobs"]:
    if j["function"] not in seen:
        seen.append(j["function"])
print("\n".join(seen))
PY
)

echo "==> Analyzing ${#FUNCS[@]} function(s) in suite '$SUITE'"
HEADER_WRITTEN=0
: > "$SUMMARY.tmp"

for fn in "${FUNCS[@]}"; do
    echo "  - $fn"
    $PYTHON scripts/collect_stats.py --suite "$SUITE" --function "$fn" \
        --metrics "$OUT/${fn}.metrics.csv" --locality "$OUT/${fn}.locality.csv"

    # Per-function classification (CSV row) appended to the summary.
    ROW=$("$DAMOV2_TOOLS_DIR/damov-classify" \
            --metrics "$OUT/${fn}.metrics.csv" \
            --locality "$OUT/${fn}.locality.csv" \
            --config host_ooo)
    if [[ $HEADER_WRITTEN -eq 0 ]]; then
        echo "$ROW" | head -1 >> "$SUMMARY.tmp"
        HEADER_WRITTEN=1
    fi
    echo "$ROW" | tail -n +2 >> "$SUMMARY.tmp"

    # Human-readable per-function report to the job log.
    "$DAMOV2_TOOLS_DIR/damov-classify" \
        --metrics "$OUT/${fn}.metrics.csv" \
        --locality "$OUT/${fn}.locality.csv" --config host_ooo --pretty
done

mv "$SUMMARY.tmp" "$SUMMARY"
echo
echo "==> Suite classification summary -> $SUMMARY"
column -t -s, "$SUMMARY" || cat "$SUMMARY"
