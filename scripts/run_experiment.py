#!/usr/bin/env python3
"""Execute DAMOV2 gem5 + Ramulator2 jobs from a run plan.

Replaces the original DAMOV workflow of hand-launching `./build/opt/zsim ...`.
Reads the plan produced by generate_configs.py and invokes gem5 for each job,
filtered by --function / --stage / --config / --cores. Use --dry-run to print
the exact gem5 command lines without executing (handy for HPC batch submission
or when gem5 is not on this machine).

Usage:
  scripts/run_experiment.py --plan out/stream/plan.json --stage trace
  scripts/run_experiment.py --plan out/stream/plan.json --stage scale \
        --function Add --cores 1,4,16,64,256 --configs host_ooo,ndp
  scripts/run_experiment.py --plan out/stream/plan.json --dry-run
"""
import argparse
import json
import os
import subprocess
import sys

import damov_common as dc


def gem5_command(cfg, job):
    gem5 = dc.abspath(cfg["gem5_binary"])
    script = dc.abspath(cfg["gem5_config"])
    ram = dc.abspath(cfg["ramulator_config"])
    outdir = job["output_dir"]
    cmd = [
        gem5, f"--outdir={outdir}", script,
        "--config", job["config"],
        "--cores", str(job["cores"]),
        "--cpu-type", job.get("cpu_type", cfg["cpu_type"]),
        "--ramulator-config", ram,
        "--cmd", dc.abspath(job["binary"]),
        "--options", job.get("options", ""),
        "--output-dir", outdir,
    ]
    if job.get("input"):
        cmd += ["--input", dc.abspath(job["input"])]
    if job["stage"] == "trace":
        cmd += ["--trace", "--trace-file", os.path.join(outdir, "trace.gz")]
    return cmd


def want(job, args):
    if args.stage and job["stage"] != args.stage:
        return False
    if args.function and job["function"] not in args.function.split(","):
        return False
    if args.configs and job["config"] not in args.configs.split(","):
        return False
    if args.cores and str(job["cores"]) not in args.cores.split(","):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--stage", choices=["trace", "scale"], default=None)
    ap.add_argument("--function", default=None, help="comma-separated names")
    ap.add_argument("--configs", default=None, help="comma-separated configs")
    ap.add_argument("--cores", default=None, help="comma-separated core counts")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--continue-on-error", action="store_true")
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    with open(args.plan) as f:
        plan = json.load(f)

    jobs = [j for j in plan["jobs"] if want(j, args)]
    if not jobs:
        dc.eprint("no jobs matched the filters")
        return 1

    rc = 0
    for i, job in enumerate(jobs, 1):
        os.makedirs(job["output_dir"], exist_ok=True)
        cmd = gem5_command(cfg, job)
        tag = f"[{i}/{len(jobs)}] {job['stage']} {job['function']} " \
              f"{job['config']}/{job['cores']}"
        if args.dry_run:
            print(tag)
            print("  " + " ".join(cmd))
            continue
        print(tag, flush=True)
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            dc.eprint(f"  FAILED (rc={proc.returncode})")
            rc = proc.returncode
            if not args.continue_on_error:
                return rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
