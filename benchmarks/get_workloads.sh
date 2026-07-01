#!/usr/bin/env bash
# Fetch the upstream application sources used by the DAMOV benchmark suite.
#
# DAMOV2 reuses the same 74 applications / 16 suites as the original DAMOV. Their
# sources (~6 GB) are distributed by the original project rather than vendored
# here. This script pulls them into ./workloads/ so you can instrument the hot
# functions with hooks/damov_hooks.h (see benchmarks/README.md).
set -euo pipefail

DEST="${1:-workloads}"
mkdir -p "$DEST"

cat <<'NOTE'
DAMOV2 does not redistribute the third-party workload sources. Obtain them from
the original DAMOV project and place them under ./workloads/:

  git clone https://github.com/CMU-SAFARI/DAMOV.git /tmp/DAMOV
  cd /tmp/DAMOV && sh get_workloads.sh      # downloads chai, ligra, parsec, ...

Then copy (or symlink) the resulting DAMOV/workloads/ into this repo's
./workloads/, and add damov_hooks.h ROI markers to each hot function you want to
characterize. The suites are: BWA, Chai, Darknet, GASE, hardware-effects, HPCC,
HPCG, Hashjoin, Ligra, Parboil, PARSEC, Phoenix, PolyBench, Rodinia, SPLASH-2,
STREAM.
NOTE

echo "Prepared workloads directory at: $DEST"
