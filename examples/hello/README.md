# DAMOV2 "hello world"

A minimal workload whose only job is to prove the DAMOV2 toolchain works. Run:

```bash
scripts/smoke_test.sh            # 20 checks across every DAMOV2 stage
scripts/smoke_test.sh --keep     # same, but keep out/hello/ to inspect
```

## Why two kernels

[hello_damov.c](hello_damov.c) has two hot functions with deliberately opposite
locality, so the correct DAMOV answer is known before anything runs — which is
what makes it a test rather than a demo:

| Kernel | Access pattern | Spatial | Temporal | Expected class |
|--------|----------------|---------|----------|----------------|
| `stream` | `c[i] = a[i] + b[i]`, sequential, no reuse | 1.0 | 0.0 (LOW) | **1a** DRAM bandwidth |
| `reuse` | sum an 8-element working set 1024 times | 1.0 | 0.5 (HIGH) | **2b** L1 cache capacity |

These are the two sides of the Fig. 26 decision tree: `stream` takes the
low-temporal-locality branch to a DRAM bottleneck (NDP is the right fix),
`reuse` takes the high-temporal-locality branch to a cache-resident one. The
measured values above are what the toolchain actually produces.

## Build flavors

The ROI hooks are the only difference between them — this is also how the test
checks that all three `damov_hooks.h` backends compile:

```bash
make native   # hooks are no-ops           -> runs on real hardware (Step 1 / VTune)
make trace    # no-ops + self-dumped trace -> Step 2 input without a simulator
make magic    # inline x86-64 m5op encodings (no libm5 needed)
make gem5 GEM5_ROOT=../../external/gem5   # real m5ops; the binary you simulate
```

The `trace` flavor writes its own memory references in DAMOV2 trace format to
`$DAMOV_TRACE_FILE`, which is how Step 2 is validated on a machine with no
simulator:

```bash
DAMOV_TRACE_FILE=/tmp/s.txt ./hello_damov_trace stream 4096
build/damov-locality --trace /tmp/s.txt --name stream --json
```

## Helpers

| File | What it does | Real or modeled |
|------|--------------|-----------------|
| [run_ramulator2.py](run_ramulator2.py) | replays a DAMOV2 trace through a real Ramulator2 memory preset and writes `ramulator_stats.yaml` | **real** DRAM simulation, open-loop request stream |
| [synth_gem5_stats.py](synth_gem5_stats.py) | derives a gem5-shaped `stats.txt` sweep from the real trace using a cold-miss model | **modeled** — a stand-in for gem5, never a result |

`run_ramulator2.py` is independently useful: it is the quickest way to check a
new memory preset elaborates and that its transaction size matches the 64-byte
cache line, which only fails at run time.

Once gem5 is built, run the real thing instead — the descriptor is
[benchmarks/hello.yaml](../../benchmarks/hello.yaml):

```bash
make gem5 GEM5_ROOT=../../external/gem5
python scripts/damov2_pipeline.py --descriptor benchmarks/hello.yaml
```

See [INSTALL.md](../../INSTALL.md) for the prerequisites each stage needs.
