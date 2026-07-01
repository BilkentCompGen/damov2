#!/usr/bin/env python3
"""Expand a benchmark descriptor into a DAMOV2 run plan.

Replaces the original DAMOV `generate_config_files.py`. Instead of emitting ZSim
`.cfg` files, it emits a JSON *run plan*: the full cross-product of
{function} x {config} x {cores} scaling jobs plus one Step-2 trace job per
function. `run_experiment.py` executes the plan against gem5 + Ramulator2.

Usage:
  scripts/generate_configs.py --descriptor benchmarks/stream.yaml [--config configs/damov.yaml]
                              [--out out/stream/plan.json]
"""
import argparse
import json
import os

import damov_common as dc


def build_plan(cfg, desc):
    suite = desc["suite"]
    jobs = []
    for fn in desc["functions"]:
        name = fn["name"]
        binary = fn.get("binary", desc.get("binary"))
        options = fn.get("options", "")
        inp = fn.get("input", "")

        # Step-2: a single-core host_ooo trace run for locality analysis.
        jobs.append({
            "stage": "trace", "suite": suite, "function": name,
            "config": "host_ooo", "cores": 1, "cpu_type": cfg["cpu_type"],
            "binary": binary, "options": options, "input": inp,
            "output_dir": dc.out_dir(cfg, suite, name, trace=True),
        })

        # Step-3: scalability sweep over configs x core counts.
        for config in cfg["configs"]:
            for cores in cfg["cores"]:
                jobs.append({
                    "stage": "scale", "suite": suite, "function": name,
                    "config": config, "cores": cores, "cpu_type": cfg["cpu_type"],
                    "binary": binary, "options": options, "input": inp,
                    "output_dir": dc.out_dir(cfg, suite, name, config, cores),
                })
    return {"suite": suite, "jobs": jobs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--descriptor", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    desc = dc.load_descriptor(dc.abspath(args.descriptor)
                              if not os.path.isabs(args.descriptor) else args.descriptor)
    plan = build_plan(cfg, desc)

    out = args.out or os.path.join(dc.abspath(cfg["output_root"]),
                                   plan["suite"], "plan.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(plan, f, indent=2)
    print(f"wrote {len(plan['jobs'])} jobs to {out}")


if __name__ == "__main__":
    main()
