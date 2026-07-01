# DAMOV2 benchmarks

DAMOV2 characterizes the same 144 hot functions from 74 applications as the
original DAMOV suite (Tables 2–7 of the paper). This directory holds **benchmark
descriptors** (the modern replacement for DAMOV's `command_files/`) that tell
the toolchain which functions to run and how.

## Descriptor format

See `stream.yaml`. Each descriptor lists the hot functions to characterize:

```yaml
suite: stream
functions:
  - name: Add                       # function / ROI name
    binary: workloads/STREAM/stream_omp
    options: ""                     # workload CLI arguments
    input: ""                       # optional stdin redirect
    class: 1a                       # expected DAMOV class (for validation)
```

Input-set sizes match the paper's Tables 2–7 (e.g. STREAM `50000000`, Ligra
`rMat`/`USA`, PolyBench `LARGE_DATASET`).

## Instrumenting a workload (Step 1 output)

Add the ROI hooks around the hot function identified by VTune:

```c
#include "damov_hooks.h"        /* -I<damov2>/hooks */

void kernel_add(double *a, double *b, double *c, size_t n) {
    damov_function_begin();     /* start of the NDP-offloadable function      */
    for (size_t i = 0; i < n; i++)
        c[i] = a[i] + b[i];
    damov_function_end();       /* end                                        */
}

int main(void) {
    /* ... allocate & init ... */
    damov_roi_begin();          /* whole region of interest                   */
    kernel_add(a, b, c, N);
    damov_roi_end();
    return 0;
}
```

Compile for detailed simulation (link gem5's libm5):

```bash
cc -O2 -I<damov2>/hooks -I<gem5>/include -DDAMOV_USE_M5OPS \
   stream.c -o stream_omp -L<gem5>/util/m5/build/x86/out -lm5
```

The **same source** compiled without `-DDAMOV_USE_M5OPS` produces a plain binary
whose hooks are no-ops — use that one for the Step-1 native VTune profiling run.

## Fetching the original workload sources

The 6 GB of upstream application sources are not vendored here. Fetch them from
the original DAMOV distribution and instrument the hot functions as above:

```bash
benchmarks/get_workloads.sh      # downloads into ./workloads/
```

## Running characterization

```bash
# whole descriptor, end to end
scripts/damov2_pipeline.py --descriptor benchmarks/stream.yaml

# or step by step
scripts/generate_configs.py --descriptor benchmarks/stream.yaml
scripts/run_experiment.py   --plan out/stream/plan.json --stage trace
scripts/run_experiment.py   --plan out/stream/plan.json --stage scale
scripts/collect_stats.py    --suite stream --function Add
build/damov-classify --metrics out/stream/Add.metrics.csv \
                     --locality out/stream/Add.locality.csv --pretty
```
