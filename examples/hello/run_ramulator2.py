#!/usr/bin/env python3
"""Drive a DAMOV2 Ramulator2 memory preset with a memory trace, without gem5.

This runs the *real* Ramulator2 simulator over a DAMOV2 trace using Ramulator2's
own trace frontend, and writes a `ramulator_stats.yaml` in the same place and
format the gem5 wrapper would. Two uses:

  * verify a memory preset actually elaborates and runs — in particular that its
    transaction size matches the 64-byte cache line (the HBM2 `channel_width`
    trap documented in CLAUDE.md), which only shows up at run time;
  * give `damov-stats --ramulator2` real DRAM counters on a machine where gem5
    is not built.

What it is NOT: a substitute for the gem5 run. There is no CPU, no cache
hierarchy and no feedback between the core and memory — the trace is replayed as
fast as the memory system accepts it. DRAM counters are real; the request stream
that produced them is open-loop.

Usage:
  examples/hello/run_ramulator2.py --trace out/hello/stream/trace/trace.txt \\
      --preset hmc --channels 2 --out out/hello/stream/trace/ramulator_stats.yaml
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "gem5", "configs"))

import ramulator2_mem  # noqa: E402


def to_loadstore(trace_path, out_path):
    """Convert a DAMOV2 text trace to Ramulator2's `LD|ST <addr>` format."""
    n = 0
    with open(trace_path) as src, open(out_path, "w") as dst:
        for raw in src:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            tok = raw.split()
            if tok[0] in ("R", "W", "r", "w"):
                op, addr = ("ST" if tok[0] in ("W", "w") else "LD"), tok[1]
            else:
                op, addr = "LD", tok[0]
            dst.write(f"{op} {addr}\n")
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="DAMOV2 text trace")
    ap.add_argument("--preset", default="hmc",
                    help="hmc | hbm2 | ddr4, or a path to a DSL/YAML config")
    ap.add_argument("--channels", type=int, default=2)
    ap.add_argument("--out", required=True, help="ramulator_stats.yaml to write")
    ap.add_argument("--ramulator-home", default=None)
    args = ap.parse_args()

    home = ramulator2_mem.ensure_ramulator_on_path(args.ramulator_home)
    try:
        import ramulator
    except ImportError as e:
        print(f"error: Ramulator2 python package not importable from {home}: {e}",
              file=sys.stderr)
        print("       build Ramulator2 first (see INSTALL.md).", file=sys.stderr)
        return 1

    mem = json.loads(ramulator2_mem.build_config_string(
        args.preset, channels=args.channels,
        ramulator_home=args.ramulator_home))["memory_system"]

    ldst = args.out + ".ldst"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    n = to_loadstore(args.trace, ldst)

    sim = ramulator.Simulation(
        frontend={"impl": "LoadStoreTrace", "clock_ratio": 1, "path": ldst},
        memory_system=mem)
    sim.run()
    sim.finalize()

    with open(args.out, "w") as f:
        f.write(sim.stats_yaml)
    os.remove(ldst)

    ms = sim.stats.get("memory_system", {})
    print(f"ramulator2 [{args.preset}]: replayed {n} accesses "
          f"({ms.get('total_num_read_requests', '?')} reads, "
          f"{ms.get('total_num_write_requests', '?')} writes) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
