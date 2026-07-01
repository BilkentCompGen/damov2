#!/usr/bin/env bash
# One-shot integration of the gem5 + Ramulator2 submodules for DAMOV2.
#
# Performs the steps from Ramulator2's README §6 (gem5 Integration):
#   1. initialize the submodules (external/gem5, external/ramulator2)
#   2. build Ramulator2            -> external/ramulator2/libramulator.so
#   3. copy the gem5 wrapper into  external/gem5/src/mem/ramulator2/
#      and point its SConscript at the Ramulator2 checkout
#   4. build gem5                  -> external/gem5/build/$ISA/gem5.opt
#
# Idempotent: re-running refreshes the wrapper and rebuilds. Tested against the
# layout Ramulator2 v2.1 ships (resources/gem5_wrappers/*, tested with gem5 v25.1).
#
# Usage:
#   scripts/setup_gem5_ramulator2.sh [ISA] [JOBS]
#   scripts/setup_gem5_ramulator2.sh X86 16
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ISA="${1:-X86}"
JOBS="${2:-$(nproc)}"
GEM5="$ROOT/external/gem5"
RAM="$ROOT/external/ramulator2"

echo "==> [1/4] Initializing submodules"
git -C "$ROOT" submodule update --init --depth 1 external/ramulator2
git -C "$ROOT" submodule update --init --depth 1 external/gem5

echo "==> [2/4] Building Ramulator2 (libramulator.so)"
cmake -S "$RAM" -B "$RAM/build" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$RAM/build" -j "$JOBS"
# The build drops libramulator.so at the ramulator2 root; verify it exists.
if [[ ! -e "$RAM/libramulator.so" ]]; then
    found=$(find "$RAM" -name 'libramulator.so' -print -quit || true)
    [[ -n "$found" ]] && ln -sf "$found" "$RAM/libramulator.so"
fi
[[ -e "$RAM/libramulator.so" ]] || { echo "libramulator.so not found after build" >&2; exit 1; }

echo "==> [3/4] Installing the gem5 wrapper into src/mem/ramulator2/"
DEST="$GEM5/src/mem/ramulator2"
mkdir -p "$DEST"
cp -v "$RAM"/resources/gem5_wrappers/{ramulator2.hh,ramulator2.cc,Ramulator2.py,SConscript} "$DEST/"
# Point the wrapper's SConscript at our Ramulator2 checkout (replace the
# placeholder RAMULATOR2_HOME line).
sed -i "s|^RAMULATOR2_HOME = .*|RAMULATOR2_HOME = '$RAM'|" "$DEST/SConscript"
echo "    RAMULATOR2_HOME set to $RAM"

echo "==> [4/4] Building gem5 ($ISA/gem5.opt)"
( cd "$GEM5" && scons "build/$ISA/gem5.opt" -j "$JOBS" --ignore-style )

cat <<EOF

Integration complete.
  gem5 binary : $GEM5/build/$ISA/gem5.opt
  ramulator2  : $RAM  (libramulator.so built)

Make Ramulator2's Python DSL importable by gem5 config scripts. DAMOV2 already
adds external/ramulator2/python to sys.path automatically, but you can also:
  export RAMULATOR2_HOME=$RAM
  export PYTHONPATH=$RAM/python:\$PYTHONPATH

If you moved libramulator.so, set at run time:
  export LD_LIBRARY_PATH=$RAM:\$LD_LIBRARY_PATH

Verify:
  $GEM5/build/$ISA/gem5.opt $ROOT/gem5/configs/damov_se.py \\
      --config host_ooo --cores 1 --cpu-type Timing --ramulator-config hmc \\
      --cmd $ROOT/workloads/STREAM/stream_omp_native --options 'add 100000' \\
      --output-dir /tmp/damov2_smoke
EOF
