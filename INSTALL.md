# DAMOV2 prerequisites — install and removal log

A record of every system package and build artifact DAMOV2 needs, so it can be
installed deliberately and **removed cleanly**. Keep this file updated when you
add a dependency.

The authoritative, machine-independent dependency list — every apt package, what
each one is for, and the two snaps that are relevant — lives in
[README.md § Dependencies](README.md#dependencies). This file covers what is
actually installed *here* and how to undo it.

Verify what currently works at any time with:

```bash
scripts/smoke_test.sh        # 25 checks; skips (not fails) on missing prereqs
```

---

## 1. Dependency tiers

DAMOV2 has three independent tiers. Each tier only needs the ones above it, so
you can stop at any tier.

| Tier | What it gets you | Needs |
|------|------------------|-------|
| **A. C++ tools + scripts** | `damov-locality`, `damov-stats`, `damov-classify`, the whole orchestration layer, Step 2 locality analysis | `build-essential`, `cmake`, `python3` |
| **B. Ramulator2** | real DRAM simulation; validates the `hmc`/`ddr4` memory presets | tier A + network (CMake `FetchContent`), `python3-dev` |
| **C. gem5** | Step 3 — the actual scalability sweep | tier B + the gem5 package list below |

Tiers A and B are cheap. **Tier C (gem5) is the only expensive one** and the
only reason you need root.

---

## 2. State on this machine (Ubuntu 24.04, as of 2026-10-19)

`sudo` requires a password here and was not used, so nothing was installed
system-wide. What follows was already present:

| Already installed (do **not** remove — predates DAMOV2) |
|---|
| `build-essential` (gcc/g++ 13.3.0), `cmake` 3.28.3, `git`, `gzip` |
| `python3` 3.12.3, `python3-dev`, `python3-pip`, `python3-yaml` |
| `zlib1g-dev` |

| Missing — needed only for gem5 (tier C) |
|---|
| `scons`, `m4`, `pkg-config`, `libprotobuf-dev`, `protobuf-compiler`, `libprotoc-dev` |
| `libgoogle-perftools-dev`, `libboost-all-dev`, `libhdf5-dev`, `libpng-dev`, `libelf-dev`, `libcapstone-dev` |
| `python3-venv`, `python3-pydot`, `python3-protobuf` |

Result: tiers A and B work fully; tier C is blocked. The smoke test reports
**20 passed, 0 failed, 2 skipped**, where the two skips are the gem5 stages.

---

## 3. Installing

### Tier A — C++ tools and scripts

Already satisfied here. On a bare machine:

```bash
sudo apt install build-essential cmake python3 python3-yaml
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
ctest --test-dir build
```

`python3-yaml` (PyYAML) is **optional** — `scripts/damov_common.py` falls back
to a built-in parser for the restricted YAML subset the configs use.

### Tier B — Ramulator2

No new system packages beyond tier A plus `python3-dev`. Ramulator2 pulls
yaml-cpp, fmt and nanobind itself via CMake `FetchContent`, so **the configure
step needs network access**; the download lands inside
`external/ramulator2/build/_deps` and is removed with that directory.

```bash
git submodule update --init --depth 1 external/ramulator2
cmake -S external/ramulator2 -B external/ramulator2/build -DCMAKE_BUILD_TYPE=Release
cmake --build external/ramulator2/build -j$(nproc)   # -> external/ramulator2/libramulator.so
```

Verify it with a real simulation, no gem5 required:

```bash
examples/hello/run_ramulator2.py --trace <a trace> --preset hmc --out /tmp/r2.yaml
```

### Tier C — gem5

**Record what you install before you install it** — this is what makes a clean
removal possible later:

```bash
apt-mark showmanual | sort > ~/apt-manual-before-damov2.txt
```

Then install the gem5 package set (Ubuntu 24.04; this is gem5's own documented
list plus `m4`, which its build requires but the docs omit):

```bash
sudo apt install scons m4 pkg-config \
    libprotobuf-dev protobuf-compiler libprotoc-dev \
    libgoogle-perftools-dev libboost-all-dev libhdf5-dev \
    libpng-dev libelf-dev libcapstone-dev \
    python3-dev python3-venv python3-pydot python3-protobuf
```

Why each is needed:

| Package | Needed for |
|---------|-----------|
| `scons` | gem5's build system |
| `m4` | gem5 build (**fatal if missing**, and absent from gem5's own list) |
| `protobuf-compiler`, `libprotobuf-dev`, `libprotoc-dev` | gem5 protobuf traces — required for `CommMonitor` trace dumping, i.e. Step 2 |
| `python3-dev` | gem5 embeds CPython; also nanobind for Ramulator2's bindings |
| `pkg-config`, `libpng-dev`, `libelf-dev`, `libcapstone-dev`, `libhdf5-dev`, `libboost-all-dev`, `libgoogle-perftools-dev` | gem5 link-time deps |
| `python3-pydot` | optional: gem5 config graph output |
| `python3-protobuf` | `scripts/proto2trace.py`, if gem5 emits protobuf traces |

Then build gem5 and wire Ramulator2 into it:

```bash
git submodule update --init --depth 1 external/gem5
scripts/setup_gem5_ramulator2.sh X86 $(nproc)       # ~30-90 min, needs ~10 GB
make -C examples/hello gem5 GEM5_ROOT=external/gem5 # the instrumented hello world
```

Capture the delta so removal is exact:

```bash
apt-mark showmanual | sort > ~/apt-manual-after-damov2.txt
comm -13 ~/apt-manual-before-damov2.txt ~/apt-manual-after-damov2.txt \
    > ~/apt-added-by-damov2.txt
cat ~/apt-added-by-damov2.txt
```

gem5 also needs `libm5` for the ROI hooks:

```bash
cd external/gem5/util/m5 && scons build/x86/out/libm5.a
```

---

## 4. Removal

### 4a. Build artifacts (no root, always safe)

None of this is tracked by git, so removing it only costs rebuild time:

```bash
rm -rf build                              # DAMOV2 C++ tools      (~2 MB)
rm -rf out                                # experiment outputs
make -C examples/hello clean              # hello-world binaries + traces
rm -rf external/ramulator2/build          # Ramulator2 objects + _deps (~17 MB)
rm -f  external/ramulator2/libramulator.so
rm -rf external/gem5/build                # gem5 objects          (~10 GB)
rm -rf external/gem5/src/mem/ramulator2   # the wrapper setup_gem5_ramulator2.sh copied in
```

To drop the vendored simulator checkouts entirely (~190 MB here):

```bash
git submodule deinit -f external/gem5 external/ramulator2
rm -rf .git/modules/external
```

### 4b. System packages (needs root)

Remove exactly what you added, using the list captured above:

```bash
sudo apt purge $(cat ~/apt-added-by-damov2.txt | tr '\n' ' ')
sudo apt autoremove --purge
```

If you did not capture that list, remove the tier-C set explicitly. **Check
nothing else needs them first** — `libboost-all-dev` and `protobuf-compiler` in
particular are common dependencies of unrelated software:

```bash
# dry run first: shows what would also be pulled out
sudo apt purge --dry-run scons m4 pkg-config \
    libprotobuf-dev protobuf-compiler libprotoc-dev \
    libgoogle-perftools-dev libboost-all-dev libhdf5-dev \
    libpng-dev libelf-dev libcapstone-dev \
    python3-venv python3-pydot python3-protobuf
```

Do **not** purge the tier-A packages listed in §2 as already installed
(`build-essential`, `cmake`, `python3*`, `zlib1g-dev`, `git`, `gzip`) — they
were on this machine before DAMOV2 and other software depends on them.

### 4c. Nothing else is touched

DAMOV2 writes only inside the repo (`build/`, `out/`, `external/*/build`,
`examples/hello/*`), plus whatever `pip`/`apt` you ran yourself. It installs no
services, no dotfiles, and no `/usr/local` files unless you run
`cmake --install`, which would place `damov-{locality,stats,classify}` and the
headers under your chosen prefix — undo that by deleting those files.

---

## 5. What you lose by stopping below tier C

Without gem5 you still get: the full C++ toolchain and its unit tests, ROI hook
compilation, **Step 2 locality analysis on real traces**, real Ramulator2 DRAM
simulation of the memory presets, metric extraction, the six-class decision
tree, and the whole plan/joblist orchestration layer (`--dry-run`).

What you cannot do: produce real gem5 `stats.txt` files, so the Step-3
scalability sweep has no measured input. `scripts/smoke_test.sh` substitutes
`examples/hello/synth_gem5_stats.py`, a documented analytic stand-in — it
exercises `damov-stats`, `collect_stats.py` and `damov-classify` on correctly
formatted inputs, but it is **not a simulation** and its numbers must never be
reported as results.
