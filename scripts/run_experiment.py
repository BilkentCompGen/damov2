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
  scripts/run_experiment.py --plan out/stream/plan.json --stage scale --jobs 24

--jobs N runs up to N gem5 processes at once. gem5 is single-threaded on the
host, so N host cores give up to N-fold speedup; host memory is the real limit
(it grows with the simulated core count; see configs/damov.yaml). With N > 1
each job's console output goes to <output_dir>/gem5.log instead of the terminal.
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys

import damov_common as dc


def gem5_command(cfg, job):
    gem5 = dc.abspath(cfg["gem5_binary"])
    script = dc.abspath(cfg["gem5_config"])
    # ramulator_config is either a preset name (hmc/hbm2/ddr4) or a config file;
    # only turn it into an absolute path when it actually names a file.
    ram = cfg["ramulator_config"]
    if os.path.exists(dc.abspath(ram)):
        ram = dc.abspath(ram)
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
    if cfg.get("ramulator_home"):
        cmd += ["--ramulator-home", dc.abspath(cfg["ramulator_home"])]
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
    ap.add_argument("--jobs", "-j", type=int, default=1,
                    help="gem5 processes to run concurrently (default 1)")
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error("--jobs must be >= 1")

    cfg = dc.load_config(args.config)
    with open(args.plan) as f:
        plan = json.load(f)

    jobs = [j for j in plan["jobs"] if want(j, args)]
    if not jobs:
        dc.eprint("no jobs matched the filters")
        return 1

    tasks = []
    for i, job in enumerate(jobs, 1):
        os.makedirs(job["output_dir"], exist_ok=True)
        tag = f"[{i}/{len(jobs)}] {job['stage']} {job['function']} " \
              f"{job['config']}/{job['cores']}"
        tasks.append((tag, job, gem5_command(cfg, job)))

    if args.dry_run:
        for tag, _, cmd in tasks:
            print(tag)
            print("  " + " ".join(cmd))
        return 0
    if args.jobs == 1:
        return run_serial(tasks, args.continue_on_error)
    return run_parallel(tasks, args.jobs, args.continue_on_error)


def run_serial(tasks, continue_on_error):
    rc = 0
    for tag, _, cmd in tasks:
        print(tag, flush=True)
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            dc.eprint(f"  FAILED (rc={proc.returncode})")
            rc = proc.returncode
            if not continue_on_error:
                return rc
    return rc


def run_parallel(tasks, n, continue_on_error):
    """Run up to n gem5 processes at once, each logging to its output dir.
    Without --continue-on-error, the first failure stops new launches (running
    jobs finish) and its return code is returned, as in the serial path."""
    def run_one(task):
        tag, job, cmd = task
        log = os.path.join(job["output_dir"], "gem5.log")
        with open(log, "w") as f:
            return tag, log, subprocess.run(cmd, stdout=f,
                                            stderr=subprocess.STDOUT).returncode

    rc = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(run_one, t) for t in tasks]
        print(f"running {len(tasks)} job(s), {n} at a time", flush=True)
        for fut in concurrent.futures.as_completed(futures):
            if fut.cancelled():
                continue
            tag, log, code = fut.result()
            if code == 0:
                print(f"{tag} done", flush=True)
                continue
            dc.eprint(f"{tag} FAILED (rc={code}); see {log}")
            if rc == 0:
                rc = code
            if not continue_on_error:
                for other in futures:
                    other.cancel()      # only not-yet-started jobs
    return rc


if __name__ == "__main__":
    sys.exit(main())
