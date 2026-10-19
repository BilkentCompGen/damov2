#!/usr/bin/env python3
"""Aggregate gem5 + Ramulator2 outputs into DAMOV2 metric tables.

Replaces the original DAMOV `get_stats_per_app.py`. For a given suite/function
it:
  * runs `damov-stats` on every scaling run's stats.txt to build a metrics CSV
    (name,config,cores,ipc,mpki,lfmr,ai,...), and optionally
  * runs `damov-locality` on the Step-2 trace to produce a locality CSV.

Usage:
  scripts/collect_stats.py --suite stream --function Add \
        --metrics out/stream/Add.metrics.csv --locality out/stream/Add.locality.csv
"""
import argparse
import os
import subprocess
import sys

import damov_common as dc


def find_ramulator_stats(outdir):
    # Ramulator2's gem5 wrapper writes its stats to ramulator_stats.yaml in the
    # gem5 output directory (alongside stats.txt).
    for name in ("ramulator_stats.yaml", "ramulator2.stats", "ramulator.stats"):
        p = os.path.join(outdir, name)
        if os.path.exists(p):
            return p
    return None


def collect_metrics(cfg, suite, function, out_csv):
    stats_tool = dc.tool(cfg, "damov-stats")
    rows = []
    header = None
    for config in cfg["configs"]:
        for cores in cfg["cores"]:
            outdir = dc.out_dir(cfg, suite, function, config, cores)
            stats = os.path.join(outdir, "stats.txt")
            if not os.path.exists(stats):
                dc.eprint(f"  missing {stats} (skipped)")
                continue
            cmd = [stats_tool, "--gem5", stats, "--config", config,
                   "--cores", str(cores), "--name", function, "--header"]
            ram = find_ramulator_stats(outdir)
            if ram:
                cmd += ["--ramulator2", ram]
            out = subprocess.run(cmd, capture_output=True, text=True)
            if out.returncode != 0:
                dc.eprint(f"  damov-stats failed for {outdir}: {out.stderr.strip()}")
                continue
            lines = out.stdout.strip().splitlines()
            if not lines:
                continue
            if header is None:
                header = lines[0]
            rows.append(lines[1] if len(lines) > 1 else lines[0])

    if header is None:
        dc.eprint(f"no stats found for {suite}:{function}")
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    with open(out_csv, "w") as f:
        f.write(header + "\n")
        f.write("\n".join(rows) + "\n")
    print(f"wrote metrics for {len(rows)} runs -> {out_csv}")
    return True


def collect_locality(cfg, suite, function, out_csv):
    loc_tool = dc.tool(cfg, "damov-locality")
    outdir = dc.out_dir(cfg, suite, function, trace=True)
    # gem5 writes trace.gz; accept the plain-text spellings too, so a trace
    # produced by hand or by a self-tracing workload is picked up as well.
    for candidate in ("trace.gz", "trace", "trace.txt"):
        trace = os.path.join(outdir, candidate)
        if os.path.exists(trace):
            break
    else:
        dc.eprint(f"no trace for {suite}:{function} at {outdir}")
        return False
    loc = cfg.get("locality", {})
    cmd = [loc_tool, "--trace", trace, "--name", function,
           "--spatial-window", str(loc.get("spatial_window", 64)),
           "--temporal-window", str(loc.get("temporal_window", 64)),
           "--granularity", str(loc.get("granularity", 8))]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        dc.eprint(f"damov-locality failed: {out.stderr.strip()}")
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    with open(out_csv, "w") as f:
        f.write(out.stdout)
    print(f"wrote locality -> {out_csv}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--function", required=True)
    ap.add_argument("--metrics", default=None, help="output metrics CSV path")
    ap.add_argument("--locality", default=None, help="output locality CSV path")
    ap.add_argument("--no-metrics", action="store_true")
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    ok = True
    if not args.no_metrics:
        out = args.metrics or os.path.join(dc.abspath(cfg["output_root"]),
                                           args.suite, f"{args.function}.metrics.csv")
        ok &= collect_metrics(cfg, args.suite, args.function, out)
    if args.locality is not None or True:
        out = args.locality or os.path.join(dc.abspath(cfg["output_root"]),
                                            args.suite, f"{args.function}.locality.csv")
        collect_locality(cfg, args.suite, args.function, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
