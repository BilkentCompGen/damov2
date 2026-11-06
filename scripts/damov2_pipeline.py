#!/usr/bin/env python3
"""End-to-end DAMOV2 driver: descriptor -> plan -> simulate -> classify.

Ties the three methodology steps together for a whole benchmark descriptor:

  1. generate_configs.py  : expand the descriptor into a run plan
  2. run_experiment.py    : Step-2 trace runs + Step-3 scalability sweep (gem5)
  3. collect_stats.py     : gem5/Ramulator2 stats -> metrics + locality CSVs
  4. damov-classify       : assign each function its bottleneck class

Usage:
  scripts/damov2_pipeline.py --descriptor benchmarks/stream.yaml
  scripts/damov2_pipeline.py --descriptor benchmarks/stream.yaml --dry-run
"""
import argparse
import os
import subprocess
import sys

import damov_common as dc
import generate_configs


def run(cmd, dry):
    print("+", " ".join(str(c) for c in cmd))
    if dry:
        return 0
    return subprocess.run([str(c) for c in cmd]).returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--descriptor", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--jobs", "-j", type=int, default=1,
                    help="gem5 processes to run concurrently (run_experiment --jobs)")
    ap.add_argument("--skip-sim", action="store_true",
                    help="reuse existing gem5 outputs; only collect + classify")
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    desc = dc.load_descriptor(dc.abspath(args.descriptor))
    suite = desc["suite"]
    here = os.path.dirname(os.path.abspath(__file__))
    # Forward --config so the sub-stages see the same output_root/paths.
    cfg_opt = ["--config", os.path.abspath(args.config)] if args.config else []

    # 1. plan
    plan = generate_configs.build_plan(cfg, desc)
    plan_path = os.path.join(dc.abspath(cfg["output_root"]), suite, "plan.json")
    os.makedirs(os.path.dirname(plan_path), exist_ok=True)
    if not args.dry_run:
        import json
        with open(plan_path, "w") as f:
            json.dump(plan, f, indent=2)
    print(f"[1/4] plan: {len(plan['jobs'])} jobs -> {plan_path}")

    # 2. simulate
    if not args.skip_sim:
        for stage in ("trace", "scale"):
            rc = run([sys.executable, os.path.join(here, "run_experiment.py"),
                      "--plan", plan_path, "--stage", stage,
                      "--continue-on-error", "--jobs", str(args.jobs)] + cfg_opt
                     + (["--dry-run"] if args.dry_run else []),
                     dry=False)
            if rc != 0 and not args.dry_run:
                dc.eprint(f"simulation stage '{stage}' returned {rc}")
    print("[2/4] simulation done")

    # 3 + 4. collect + classify per function
    classify_tool = dc.tool(cfg, "damov-classify")
    th = cfg.get("thresholds", {})
    for fn in desc["functions"]:
        name = fn["name"]
        metrics = os.path.join(dc.abspath(cfg["output_root"]), suite, f"{name}.metrics.csv")
        locality = os.path.join(dc.abspath(cfg["output_root"]), suite, f"{name}.locality.csv")
        run([sys.executable, os.path.join(here, "collect_stats.py"),
             "--suite", suite, "--function", name,
             "--metrics", metrics, "--locality", locality] + cfg_opt,
            dry=args.dry_run)
        run([classify_tool, "--metrics", metrics, "--locality", locality,
             "--config", cfg["classify_config"],
             "--tl-th", th.get("temporal_locality", 0.48),
             "--lfmr-th", th.get("lfmr", 0.56),
             "--mpki-th", th.get("mpki", 11.0),
             "--ai-th", th.get("ai", 8.5),
             "--trend-delta", th.get("trend_delta", 0.10),
             "--pretty"], dry=args.dry_run)
    print("[4/4] classification done")


if __name__ == "__main__":
    main()
