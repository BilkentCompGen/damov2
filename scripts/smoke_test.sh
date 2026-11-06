#!/usr/bin/env bash
# DAMOV2 smoke test — does the toolchain work end to end?
#
# Runs the hello-world example (examples/hello) through every DAMOV2 stage and
# checks the results against the classes the two kernels are known to belong to:
#
#   stream : sequential, no reuse       -> spatial 1.0, temporal 0.0 -> class 1a
#   reuse  : tiny working set, hammered -> temporal 0.5, low AI      -> class 2b
#
# Stages are labeled REAL (the actual simulator/tool ran) or MODEL (a documented
# stand-in because the simulator is not built here). Stages whose prerequisites
# are missing SKIP rather than fail, so this is useful on a bare machine too.
#
# Usage:
#   scripts/smoke_test.sh            # run everything available
#   scripts/smoke_test.sh --keep     # keep the out/hello tree for inspection
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

KEEP=0
[[ "${1:-}" == "--keep" ]] && KEEP=1

PASS=0; FAIL=0; SKIP=0
RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLD=$'\033[1m'; RST=$'\033[0m'

stage() { printf "\n${BLD}== %s${RST}\n" "$*"; }
pass()  { PASS=$((PASS+1)); printf "  ${GRN}PASS${RST}  %s\n" "$*"; }
fail()  { FAIL=$((FAIL+1)); printf "  ${RED}FAIL${RST}  %s\n" "$*"; }
skip()  { SKIP=$((SKIP+1)); printf "  ${YLW}SKIP${RST}  %s\n" "$*"; }

# check_num <label> <actual> <lo> <hi>  — pass if lo <= actual <= hi
check_num() {
    local label=$1 val=$2 lo=$3 hi=$4
    if [[ -z "$val" ]]; then fail "$label (no value produced)"; return; fi
    if awk -v v="$val" -v l="$lo" -v h="$hi" 'BEGIN{exit !(v>=l && v<=h)}'; then
        pass "$label = $val (expected $lo..$hi)"
    else
        fail "$label = $val (expected $lo..$hi)"
    fi
}

check_str() {
    local label=$1 val=$2 want=$3
    if [[ "$val" == "$want" ]]; then pass "$label = $val"
    else fail "$label = '$val' (expected '$want')"; fi
}

OUT="$ROOT/out/hello"
TOOLS="$ROOT/build"

# --------------------------------------------------------------------------- #
stage "1. DAMOV2 C++ tools [REAL]"
# --------------------------------------------------------------------------- #
if cmake -S . -B build -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1 \
   && cmake --build build -j"$(nproc)" >/dev/null 2>&1; then
    pass "build (damov-locality, damov-stats, damov-classify)"
else
    fail "build failed — run: cmake -S . -B build && cmake --build build"
    printf "\nCannot continue without the tools.\n"; exit 1
fi
if ctest --test-dir build --output-on-failure >/dev/null 2>&1; then
    pass "unit tests (locality, classify, metrics)"
else
    fail "unit tests — run: ctest --test-dir build --output-on-failure"
fi

# --------------------------------------------------------------------------- #
stage "2. ROI hook backends compile [REAL]"
# --------------------------------------------------------------------------- #
if make -C examples/hello all >/dev/null 2>&1; then
    pass "hooks: no-op (native), self-trace, inline magic m5ops"
else
    fail "hello-world build — run: make -C examples/hello all"
fi
if make -C examples/hello gem5 GEM5_ROOT="$ROOT/external/gem5" >/dev/null 2>&1; then
    pass "hooks: libm5 m5ops (gem5 flavor)"
else
    skip "hooks: libm5 m5ops — gem5's libm5 not built (see INSTALL.md)"
fi

# --------------------------------------------------------------------------- #
stage "3. Workload runs natively [REAL]"
# --------------------------------------------------------------------------- #
# Capture then grep (not `... | grep -q`): see the note at stage 9 — grep -q
# closing the pipe early can make the producer exit non-zero under pipefail.
mkdir -p "$OUT"
if examples/hello/hello_damov_native stream 4096 >"$OUT/native.out" 2>/dev/null \
   && grep -q "hello, DAMOV2" "$OUT/native.out"; then
    pass "hello_damov_native stream (ROI hooks are no-ops off-simulator)"
else
    fail "hello_damov_native did not run"
fi

# --------------------------------------------------------------------------- #
stage "4. Step 2 — memory trace + locality [REAL]"
# --------------------------------------------------------------------------- #
declare -A TRACE
for fn in stream reuse; do
    d="$OUT/$fn/trace"; mkdir -p "$d"
    TRACE[$fn]="$d/trace.txt"
    case $fn in
        stream) argv=(stream 4096) ;;
        reuse)  argv=(reuse 8 1024) ;;
    esac
    if DAMOV_TRACE_FILE="${TRACE[$fn]}" examples/hello/hello_damov_trace "${argv[@]}" \
         >/dev/null 2>&1 && [[ -s "${TRACE[$fn]}" ]]; then
        pass "$fn: trace dumped ($(wc -l < "${TRACE[$fn]}") accesses)"
    else
        fail "$fn: trace not produced"
    fi
done

# damov-locality on the real traces, checked against the paper's conventions.
loc() { "$TOOLS/damov-locality" --trace "$1" --name "$2" --json 2>/dev/null \
        | sed -n "s/.*\"$3\": *\([^,]*\),*\$/\1/p"; }

check_num "stream spatial locality (sequential => 1.0)" \
          "$(loc "${TRACE[stream]}" stream spatial_locality)" 0.95 1.0
check_num "stream temporal locality (no reuse => 0.0, LOW)" \
          "$(loc "${TRACE[stream]}" stream temporal_locality)" 0.0 0.1
check_num "reuse temporal locality (hammered => HIGH, >0.48)" \
          "$(loc "${TRACE[reuse]}" reuse temporal_locality)" 0.48 1.0

# --------------------------------------------------------------------------- #
stage "5. Ramulator2 memory configs [REAL]"
# --------------------------------------------------------------------------- #
if [[ -e external/ramulator2/libramulator.so ]]; then
    for preset in hmc ddr4; do
        if python3 examples/hello/run_ramulator2.py --trace "${TRACE[stream]}" \
              --preset "$preset" --channels 2 \
              --out "$OUT/stream/trace/ramulator_stats_$preset.yaml" >/dev/null 2>&1; then
            pass "$preset preset elaborates and replays the trace (64 B transactions)"
        else
            fail "$preset preset failed — rerun without >/dev/null to see the error"
        fi
    done
    # The gem5 wrapper writes this name; damov-stats looks for it.
    cp -f "$OUT/stream/trace/ramulator_stats_hmc.yaml" \
          "$OUT/stream/trace/ramulator_stats.yaml" 2>/dev/null
else
    skip "Ramulator2 not built — cmake -S external/ramulator2 -B external/ramulator2/build && cmake --build external/ramulator2/build"
fi

# --------------------------------------------------------------------------- #
stage "6. Step 3 — gem5 scalability sweep"
# --------------------------------------------------------------------------- #
GEM5_BIN="${DAMOV2_GEM5_BIN:-external/gem5/build/X86/gem5.opt}"
if [[ -x "$GEM5_BIN" ]]; then
    python3 scripts/generate_configs.py --descriptor benchmarks/hello.yaml >/dev/null \
      && python3 scripts/run_experiment.py --plan out/hello/plan.json --stage scale \
             --continue-on-error >/dev/null 2>&1 \
      && pass "gem5 sweep executed [REAL]" || fail "gem5 sweep failed [REAL]"
else
    skip "gem5 not built ($GEM5_BIN) — using the modeled stand-in below [MODEL]"
    # stream: 1 FP add per 3 accesses. reuse: 1 FP add per access.
    python3 examples/hello/synth_gem5_stats.py --trace "${TRACE[stream]}" \
        --suite hello --function stream --arith-per-access 0.33 >/dev/null 2>&1 \
      && pass "stream: stats.txt sweep synthesized [MODEL]" \
      || fail "stream: could not synthesize stats [MODEL]"
    python3 examples/hello/synth_gem5_stats.py --trace "${TRACE[reuse]}" \
        --suite hello --function reuse --arith-per-access 1.0 >/dev/null 2>&1 \
      && pass "reuse: stats.txt sweep synthesized [MODEL]" \
      || fail "reuse: could not synthesize stats [MODEL]"
fi

# --------------------------------------------------------------------------- #
stage "7. Metric extraction — damov-stats via collect_stats.py [REAL]"
# --------------------------------------------------------------------------- #
for fn in stream reuse; do
    if python3 scripts/collect_stats.py --suite hello --function "$fn" \
          --metrics "$OUT/$fn.metrics.csv" --locality "$OUT/$fn.locality.csv" \
          >/dev/null 2>&1 && [[ -s "$OUT/$fn.metrics.csv" ]]; then
        pass "$fn: metrics CSV ($(( $(wc -l < "$OUT/$fn.metrics.csv") - 1 )) sweep points)"
    else
        fail "$fn: metrics CSV not produced"
    fi
done

# --------------------------------------------------------------------------- #
stage "8. Step 3 — classification [REAL]"
# --------------------------------------------------------------------------- #
cls() {
    "$TOOLS/damov-classify" --metrics "$OUT/$1.metrics.csv" \
        --locality "$OUT/$1.locality.csv" --config host_ooo --json 2>/dev/null \
        | sed -n 's/.*"class": *"\([^"]*\)".*/\1/p'
}
check_str "stream class (expect DRAM bandwidth)" "$(cls stream)" "1a"
check_str "reuse class (expect L1 cache capacity)" "$(cls reuse)" "2b"

# --------------------------------------------------------------------------- #
stage "9. Orchestration — plan + gem5 command construction [REAL]"
# --------------------------------------------------------------------------- #
if python3 scripts/generate_configs.py --descriptor benchmarks/hello.yaml \
       --out "$OUT/plan.json" >/dev/null 2>&1; then
    njobs=$(python3 -c "import json;print(len(json.load(open('$OUT/plan.json'))['jobs']))")
    # 2 functions x (1 trace + 3 configs x 4 core counts) = 26
    check_num "plan job count" "$njobs" 26 26
else
    fail "generate_configs.py failed"
fi
# Capture to files rather than piping into `grep -q`: with `set -o pipefail`,
# grep -q closes the pipe on its first match while run_experiment is still
# printing the remaining jobs, so Python hits a broken pipe and exits non-zero —
# and whether that surfaces is Python/OS-dependent, so the pipeline flakes across
# machines. Writing to a file and grepping it is deterministic everywhere.
dry_out="$OUT/dry-run.out"; dry_err="$OUT/dry-run.stderr"
if python3 scripts/run_experiment.py --plan "$OUT/plan.json" --dry-run \
       >"$dry_out" 2>"$dry_err" && grep -q -- "--ramulator-config" "$dry_out"; then
    pass "gem5 command lines constructed (--dry-run)"
else
    fail "run_experiment.py --dry-run produced no gem5 commands"
    # Surface the hidden cause instead of leaving the user to guess.
    [[ -s "$dry_err" ]] && sed 's/^/        /' "$dry_err" >&2
fi
if python3 scripts/export_joblist.py --plan "$OUT/plan.json" \
       --out "$OUT/joblist.txt" >/dev/null 2>&1 && [[ -s "$OUT/joblist.txt" ]]; then
    pass "SLURM joblist exported ($(wc -l < "$OUT/joblist.txt") lines)"
else
    fail "export_joblist.py failed"
fi

# --------------------------------------------------------------------------- #
stage "10. Migration from original DAMOV (command file -> descriptor) [REAL]"
# --------------------------------------------------------------------------- #
# A DAMOV command file + generator in miniature: PIM_ROOT and THREADS must turn
# into a descriptor whose plan carries the per-job core count in the options.
MIG="$OUT/migrate"; rm -rf "$MIG"; mkdir -p "$MIG"   # fresh: a --keep run leaves outputs
printf 'hello,Hello,stream,PIM_ROOT/hello_damov stream 4096 THREADS\n' >"$MIG/hello_cf"
printf 'number_of_cores = [1, 8]\nversions = ["ooo"]\nplatforms = ["host_{0}/no_prefetch", "pim_{0}"]\n' \
    >"$MIG/generate_config_files.py"
if python3 scripts/migrate_damov.py "$MIG/hello_cf" --generator "$MIG/generate_config_files.py" \
       --pim-root '{root}/examples/hello' --out-dir "$MIG" --config-prefix "$MIG/cfg" \
       >"$MIG/migrate.out" 2>&1 \
   && DAMOV2_OUTPUT_ROOT="$MIG/out" python3 scripts/generate_configs.py \
       --descriptor "$MIG/hello.yaml" --config "$MIG/cfg_ooo.yaml" \
       --out "$MIG/plan.json" >/dev/null 2>&1; then
    pass "migrate_damov.py: command file + generator -> descriptor + config"
    # 1 function x (1 trace + 2 configs x 2 core counts) = 5
    njobs=$(python3 -c "import json;print(len(json.load(open('$MIG/plan.json'))['jobs']))")
    check_num "migrated plan job count" "$njobs" 5 5
    # Compare resolved paths: {root} comes from Python's cwd, which resolves
    # symlinks, while $ROOT is bash's logical pwd (e.g. a symlinked home).
    opts=$(python3 -c "import json, os
j=[x for x in json.load(open('$MIG/plan.json'))['jobs'] if x['cores']==8][0]
same=os.path.realpath(j['binary'])==os.path.realpath('$ROOT/examples/hello/hello_damov')
print(j['options'] if same else 'bad binary '+j['binary'])")
    check_str "THREADS/PIM_ROOT expanded (8-core job)" "$opts" "stream 4096 8"
else
    fail "migrate_damov.py pipeline failed"
    sed 's/^/        /' "$MIG/migrate.out" >&2
fi
if cc -Wall -Wextra -Werror -Ihooks/compat -Ihooks -x c - -o "$MIG/zsim_compat" \
       >/dev/null 2>&1 <<'EOF'
#include "zsim_hooks.h"
int main(void)
{
    zsim_roi_begin(); zsim_PIM_function_begin();
    zsim_PIM_function_end(); zsim_roi_end();
    zsim_begin(); zsim_end(); zsim_heartbeat();
    return 0;
}
EOF
then
    pass "hooks/compat/zsim_hooks.h builds DAMOV-instrumented code"
else
    fail "hooks/compat/zsim_hooks.h does not compile"
fi

# --------------------------------------------------------------------------- #
printf "\n${BLD}================ summary ================${RST}\n"
printf "  ${GRN}passed  %d${RST}\n  ${RED}failed  %d${RST}\n  ${YLW}skipped %d${RST}\n" \
       "$PASS" "$FAIL" "$SKIP"
if (( SKIP > 0 )); then
    printf "\nSkipped stages need prerequisites that are not installed; see INSTALL.md.\n"
fi
if (( KEEP )); then
    printf "Artifacts kept in %s\n" "$OUT"
else
    rm -rf "$OUT"; make -C examples/hello clean >/dev/null 2>&1
    printf "Artifacts cleaned (use --keep to retain them).\n"
fi
(( FAIL == 0 )) || exit 1
printf "\n${GRN}DAMOV2 works as intended.${RST}\n"
