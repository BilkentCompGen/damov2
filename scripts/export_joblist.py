#!/usr/bin/env python3
"""Flatten a DAMOV2 run plan into a plain joblist for SLURM array jobs.

Each output line is one fully-formed gem5 command (the same one
run_experiment.py would execute). A SLURM array task N then runs line N. This
keeps the cluster submission trivial: one array task == one gem5 simulation.

Usage:
  scripts/export_joblist.py --plan out/stream/plan.json --out out/stream/joblist.txt
  scripts/export_joblist.py --plan out/stream/plan.json --stage scale --out jobs.txt
"""
import argparse
import json
import os
import shlex
import sys

import damov_common as dc
import run_experiment


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", choices=["trace", "scale"], default=None,
                    help="restrict to one stage (default: all jobs)")
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    with open(args.plan) as f:
        plan = json.load(f)

    jobs = [j for j in plan["jobs"] if not args.stage or j["stage"] == args.stage]

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        for job in jobs:
            os.makedirs(job["output_dir"], exist_ok=True)
            cmd = run_experiment.gem5_command(cfg, job)
            f.write(" ".join(shlex.quote(str(c)) for c in cmd) + "\n")

    print(f"wrote {len(jobs)} job command(s) -> {args.out}")
    print(f"SLURM array range: 0-{len(jobs) - 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
