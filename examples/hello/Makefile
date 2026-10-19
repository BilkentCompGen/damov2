# Build the DAMOV2 "hello world" workload in its three ROI-hook flavors.
#
#   make native   hello_damov_native  — hooks are no-ops; runs on real hardware
#   make trace    hello_damov_trace   — no-op hooks + self-dumped memory trace
#   make magic    hello_damov_magic   — inline x86-64 m5op encodings (no libm5)
#   make gem5     hello_damov         — real m5ops, links gem5's libm5
#
# `make all` builds everything that can be built here: native, trace and magic
# need nothing but a C compiler; gem5 needs a gem5 checkout:
#
#   make gem5 GEM5_ROOT=../../external/gem5
#
# Override the m5 library location if your gem5 built it elsewhere:
#   make gem5 GEM5_ROOT=/opt/gem5 M5_LIBDIR=/opt/gem5/util/m5/build/x86/out

CC        ?= gcc
DAMOV2    ?= ../..
HOOKS_DIR := $(DAMOV2)/hooks

GEM5_ROOT ?= $(DAMOV2)/external/gem5
M5_INCDIR ?= $(GEM5_ROOT)/include
M5_LIBDIR ?= $(GEM5_ROOT)/util/m5/build/x86/out

CFLAGS  ?= -O2 -std=c11 -Wall -Wextra
INCLUDE := -I$(HOOKS_DIR)

BINARIES := hello_damov_native hello_damov_trace hello_damov_magic

.PHONY: all native trace magic gem5 clean
all: $(BINARIES)

native: hello_damov_native
trace:  hello_damov_trace
magic:  hello_damov_magic
gem5:   hello_damov

# No-op hooks: the Step-1 native profiling binary.
hello_damov_native: hello_damov.c
	$(CC) $(CFLAGS) $(INCLUDE) $< -o $@

# No-op hooks + self-dumped memory trace: the Step-2 input without a simulator.
hello_damov_trace: hello_damov.c
	$(CC) $(CFLAGS) $(INCLUDE) -DDAMOV_SELF_TRACE $< -o $@

# Inline m5op magic instructions: verifies the libm5-free hook backend builds.
hello_damov_magic: hello_damov.c
	$(CC) $(CFLAGS) $(INCLUDE) -DDAMOV_USE_MAGIC $< -o $@

# Real m5ops against gem5's libm5: the binary you simulate.
hello_damov: hello_damov.c
	@test -f "$(M5_INCDIR)/gem5/m5ops.h" || { \
	    echo "error: $(M5_INCDIR)/gem5/m5ops.h not found."; \
	    echo "       set GEM5_ROOT to a gem5 checkout (see INSTALL.md)."; exit 1; }
	@test -f "$(M5_LIBDIR)/libm5.a" || { \
	    echo "error: $(M5_LIBDIR)/libm5.a not found."; \
	    echo "       build it: make -C $(GEM5_ROOT)/util/m5 build/x86/out/libm5.a"; \
	    echo "       (or: cd $(GEM5_ROOT)/util/m5 && scons build/x86/out/libm5.a)"; exit 1; }
	$(CC) $(CFLAGS) $(INCLUDE) -I$(M5_INCDIR) -DDAMOV_USE_M5OPS \
	    $< -o $@ -L$(M5_LIBDIR) -lm5

clean:
	rm -f $(BINARIES) hello_damov hello_trace*.txt
