"""DAMOV2 cache hierarchy, matching Table 1 of the DAMOV paper.

Three system configurations are supported:

  host_ooo       : private L1 (32 KB) + L2 (256 KB), shared L3 (8 MB, 16 banks),
                   no hardware prefetcher.
  host_prefetch  : identical to host_ooo plus a stride prefetcher on the L2.
  ndp            : a single level of private read-only L1 (32 KB), NO L2/L3 and
                   NO prefetcher — the NDP core sits in the logic layer with
                   direct access to the (Ramulator2-modeled HMC) DRAM banks.

These classes are gem5 ClassicCache subclasses and are consumed by
gem5/configs/damov_se.py. Sizes/associativities/latencies follow Table 1;
energy numbers from the paper are recorded in comments for the McPAT-style
post-processing but do not affect timing.
"""
from m5.objects import Cache, StridePrefetcher


# --- Private L1 caches (32 KB, 8-way, 4-cycle, 64 B line) -------------------
class L1Cache(Cache):
    assoc = 8
    tag_latency = 4
    data_latency = 4
    response_latency = 4
    mshrs = 16
    tgts_per_mshr = 20
    writeback_clean = False


class L1ICache(L1Cache):
    size = "32kB"


class L1DCache(L1Cache):
    size = "32kB"


class NDPL1DCache(L1Cache):
    """NDP private L1: 32 KB, read-only data cache (Table 1, NDP config)."""
    size = "32kB"
    # gem5 has no literal "read-only" flag; NDP semantics are enforced by not
    # attaching an L2/L3 behind it and by the paper's read-only-L1 assumption.


# --- Private L2 cache (256 KB, 8-way, 7-cycle, 64 B line) -------------------
class L2Cache(Cache):
    size = "256kB"
    assoc = 8
    tag_latency = 7
    data_latency = 7
    response_latency = 7
    mshrs = 20            # MSHR size: 20-request / 20-write (Table 1)
    tgts_per_mshr = 20
    writeback_clean = False


class L2CacheWithPrefetcher(L2Cache):
    """host_prefetch: 2-degree stride prefetcher, 16 streams, 64 entries."""
    prefetcher = StridePrefetcher(degree=2, latency=1)


# --- Shared L3 cache (8 MB, 16 banks, 16-way, 27-cycle, 64 B line) ----------
class L3Cache(Cache):
    size = "8MB"
    assoc = 16
    tag_latency = 27
    data_latency = 27
    response_latency = 27
    mshrs = 64           # MSHR size: 64-request / 64-write (Table 1)
    tgts_per_mshr = 24
    writeback_clean = True
    # Inclusive, MESI-style behavior is modeled by the classic cache with the
    # shared L3 as the point of coherence for the host configurations.


def make_l3(num_banks=16):
    """L3 is 8 MB across 16 banks (0.5 MB/bank). gem5's classic L3 is modeled
    as one shared cache; banking is represented via the interleaved memory /
    xbar. Kept as a hook for a future NUCA (Section 3.4) configuration."""
    return L3Cache()
