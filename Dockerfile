# DAMOV2 in a container.
#
# The whole DAMOV2 toolchain is userspace — the C++ tools, Ramulator2 and gem5
# SE-mode all run without any privileged or low-level host access, so this image
# needs no --privileged, no extra capabilities and no host devices. The only part
# of the methodology that needs bare metal is Step 1 (Intel VTune, which reads
# hardware performance counters); DAMOV2 does not automate it and consumes only
# its output (an ROI-annotated binary), so Steps 2 and 3 containerize fully.
#
# Two things the container still needs:
#   * network at BUILD time   — git submodule fetch + Ramulator2's CMake
#                               FetchContent (yaml-cpp, fmt, nanobind).
#   * memory at RUN time       — a 256-core O3 sweep wants ~60 GB+ RAM; even the
#                               default {1,4,16,64} sweep is memory-hungry. Give
#                               the container (and Docker itself) enough headroom
#                               or it will OOM, exactly as on bare metal.
#
# Build (slow: gem5 compiles from source — tens of minutes, several GB of RAM):
#   docker build -t damov2 .
#   docker build -t damov2 --build-arg JOBS=16 --build-arg ISA=X86 .
#
# Run:
#   docker run --rm -it damov2                          # shell in the repo
#   docker run --rm -it damov2 scripts/smoke_test.sh    # full end-to-end check
#
# --------------------------------------------------------------------------- #
# Stage 1: builder — full toolchain, compiles everything.
# --------------------------------------------------------------------------- #
FROM ubuntu:24.04 AS builder

ARG ISA=X86
ARG JOBS=4
ENV DEBIAN_FRONTEND=noninteractive

# The complete tier A+B+C dependency set (see README.md § Dependencies).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git gzip m4 pkg-config scons ca-certificates \
        python3 python3-dev python3-venv python3-pip \
        python3-yaml python3-pydot python3-protobuf \
        zlib1g-dev libprotobuf-dev protobuf-compiler libprotoc-dev \
        libboost-all-dev libhdf5-dev libpng-dev libelf-dev libcapstone-dev \
        libgoogle-perftools-dev libgtest-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/damov2
COPY . .

# Submodules are fetched fresh here (the build context ships .git + .gitmodules
# but not the submodule working trees — see .dockerignore), so the image always
# builds the pinned gem5 v25.1 / Ramulator2 v2.1.0 commits regardless of host
# state. Files are root-owned inside the container, so mark the tree safe.
RUN git config --global --add safe.directory '*' \
    && git submodule update --init --depth 1 external/ramulator2 external/gem5

# Tier A — DAMOV2 C++ tools, gated by the unit tests.
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j"${JOBS}" \
    && (cd build && ctest --output-on-failure)

# Tier B + C — Ramulator2 (libramulator.so) and gem5 (gem5.opt), wired together.
RUN scripts/setup_gem5_ramulator2.sh "${ISA}" "${JOBS}"

# libm5 + the instrumented hello-world binaries, so the image is ready to run
# the pipeline (and the smoke test) without a rebuild.
RUN cd external/gem5/util/m5 && scons build/x86/out/libm5.a -j"${JOBS}" || true
RUN make -C examples/hello all \
    && make -C examples/hello gem5 GEM5_ROOT=/opt/damov2/external/gem5 || true

# Drop gem5's intermediate object files: gem5.opt is already linked, and the .o
# tree is multiple GB that the runtime stage never needs.
RUN find external/gem5/build -name '*.o' -delete \
    && find external/gem5/build -name '*.os' -delete

# --------------------------------------------------------------------------- #
# Stage 2: runtime — slim image with just the libraries the built binaries load.
# --------------------------------------------------------------------------- #
FROM ubuntu:24.04 AS runtime

ARG ISA=X86
ENV DEBIAN_FRONTEND=noninteractive

# No scons / m4 / protobuf-compiler / git: the smoke test never rebuilds gem5 or
# Ramulator2 (it uses the prebuilt gem5.opt and libramulator.so). It does, though,
# recompile the C++ tools and the hello-world workload from scratch, so keep
# build-essential + cmake. The -dev library packages are a convenient superset
# that guarantees the exact shared objects gem5.opt and libramulator.so link
# against are present.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake \
        python3 python3-dev python3-yaml python3-pydot python3-protobuf \
        gzip ca-certificates \
        zlib1g-dev libprotobuf-dev \
        libboost-all-dev libhdf5-dev libpng-dev libelf-dev libcapstone-dev \
        libgoogle-perftools-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/damov2
COPY --from=builder /opt/damov2 /opt/damov2

# damov-* tools on PATH, Ramulator2's shared lib + Python DSL discoverable.
ENV PATH=/opt/damov2/build:${PATH} \
    LD_LIBRARY_PATH=/opt/damov2/external/ramulator2 \
    PYTHONPATH=/opt/damov2/external/ramulator2/python \
    DAMOV2_GEM5_BIN=/opt/damov2/external/gem5/build/${ISA}/gem5.opt

CMD ["/bin/bash"]
