#!/usr/bin/env python3
"""Synthesize a gem5-shaped stats.txt sweep for the hello-world example.

WHY THIS EXISTS
---------------
Step 3 of the DAMOV methodology needs a gem5 `stats.txt` per (config, cores)
point. Building gem5 is heavy (see INSTALL.md), so this script stands in for it
so the rest of the toolchain — `damov-stats`, `collect_stats.py` and
`damov-classify` — can be exercised on a machine without gem5.

It is a STAND-IN, NOT A SIMULATION. It does not model timing, contention,
prefetching or the memory system. Once gem5 is built, delete the synthesized
`out/` tree and let `run_experiment.py` produce real stats.txt files instead;
nothing downstream changes, because the file format is identical.

WHAT IT MODELS
--------------
Everything is derived from the *real* memory trace the hello-world workload
dumped, so the numbers follow the kernel's actual behavior rather than being
invented:

  * L1 accesses  = number of accesses in the trace
  * L1 misses    = number of distinct 64-byte lines the trace touches
                   (a cold-miss model: each line is fetched exactly once)
  * LLC misses   = L1 misses — cold misses are not absorbed by L2/L3, they all
                   reach DRAM
  * instructions = `--insts-per-access` x accesses (loop overhead + address
                   arithmetic around each memory op)
  * arithmetic   = `--arith-per-access` x accesses (the kernel's op:access
                   ratio, e.g. stream does one FP add per three accesses)
  * cycles       = instructions / `--ipc`

For the core sweep this is weak scaling: every core runs the same work, so the
absolute counters scale with the core count while the DAMOV *ratios* (MPKI,
LFMR, AI) stay constant. A constant LFMR across cores is exactly the
"LFMR high/constant" leg of the decision tree, which is what the two
hello-world kernels should take.

Usage:
  synth_gem5_stats.py --trace out/hello/stream/trace/trace.txt \\
      --suite hello --function stream --arith-per-access 0.33
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "scripts"))
import damov_common as dc  # noqa: E402

LINE_BYTES = 64


def scan_trace(path):
    """Return (accesses, distinct 64 B lines) for a DAMOV2 text trace."""
    accesses = 0
    lines = set()
    with open(path) as f:
        for raw in f:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            tok = raw.split()
            # Formats: "ADDR" | "R ADDR SIZE" | "ADDR SIZE"
            addr_tok = tok[1] if tok[0] in ("R", "W", "r", "w") else tok[0]
            addr = int(addr_tok, 16) if addr_tok.lower().startswith("0x") else int(addr_tok)
            accesses += 1
            lines.add(addr // LINE_BYTES)
    return accesses, len(lines)


def write_stats(path, cores, accesses, l1_misses, insts, arith, cycles):
    """Write one gem5-format stats.txt with DAMOV2's default stat names."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n---------- Begin Simulation Statistics ----------\n")
        f.write(f"simInsts {insts * cores:.0f}\n")
        f.write(f"simTicks {cycles * 500:.0f}\n")
        for c in range(cores):
            f.write(f"system.cpu{c}.numCycles {cycles:.0f}\n")
            f.write(f"system.cpu{c}.dcache.overallAccesses::total {accesses:.0f}\n")
            f.write(f"system.cpu{c}.dcache.overallMisses::total {l1_misses:.0f}\n")
            # The hello-world kernels are tight loops: instruction-cache misses
            # are negligible, but the stat must exist for the parser to find it.
            f.write(f"system.cpu{c}.icache.overallMisses::total 0\n")
            f.write(f"system.cpu{c}.committedInstType::IntAlu {insts - arith:.0f}\n")
            f.write(f"system.cpu{c}.committedInstType::FloatAdd {arith:.0f}\n")
        # Shared LLC: cold misses all reach DRAM.
        f.write(f"system.l3.overallMisses::total {l1_misses * cores:.0f}\n")
        f.write("---------- End Simulation Statistics   ----------\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="DAMOV2 text trace to model")
    ap.add_argument("--suite", required=True)
    ap.add_argument("--function", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--insts-per-access", type=float, default=2.0)
    ap.add_argument("--arith-per-access", type=float, default=0.33,
                    help="kernel arithmetic ops per memory access")
    ap.add_argument("--ipc", type=float, default=0.5)
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    accesses, l1_misses = scan_trace(args.trace)
    insts  = args.insts_per_access * accesses
    arith  = args.arith_per_access * accesses
    cycles = insts / args.ipc

    written = 0
    for config in cfg["configs"]:
        for cores in cfg["cores"]:
            outdir = dc.out_dir(cfg, args.suite, args.function, config, cores)
            write_stats(os.path.join(outdir, "stats.txt"), cores,
                        accesses, l1_misses, insts, arith, cycles)
            written += 1

    mpki = l1_misses / (insts / 1000.0) if insts else 0
    lfmr = l1_misses / l1_misses if l1_misses else 0
    ai   = arith / accesses if accesses else 0
    print(f"synthesized {written} stats.txt for {args.suite}:{args.function} "
          f"(accesses={accesses}, lines={l1_misses})")
    print(f"  implied metrics: MPKI={mpki:.2f} LFMR={lfmr:.2f} AI={ai:.2f}")


if __name__ == "__main__":
    main()
