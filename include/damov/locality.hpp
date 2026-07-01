// locality.hpp — architecture-independent spatial & temporal locality (Step 2).
//
// Implements the two metrics defined in the DAMOV paper (Section 2.3):
//
//   Spatial Locality  (Eq. 1):
//       For every window of W memory references, compute the minimum distance
//       (stride) between any two addresses in the window. Build a stride
//       histogram; stride_profile(i) is the fraction of windows whose minimum
//       stride equals i. Then
//                 SpatialLocality = Σ_i stride_profile(i) / i
//       A value near 1 => sequential access; near 0 => large/irregular strides.
//
//   Temporal Locality (Eq. 2):
//       Within a sliding window of L memory references, count how many times
//       each address is repeated. For an address repeated N times, increment
//       reuse_profile(floor(log2 N)). Then
//                 TemporalLocality = Σ_i 2^i * reuse_profile(i) / total_accesses
//       A value near 1 => very high reuse; near 0 => no reuse.
//
// Both metrics are computed at a configurable address granularity (default:
// per-byte, i.e. strides are in bytes). Setting `granularity` to the dominant
// element size reproduces the paper's "sequential access -> 1.0" convention;
// setting it to the cache-line size measures line-granularity locality. The
// window sizes W and L are configurable; the paper reports results are stable
// across {8,16,32,64,128}.
#ifndef DAMOV_LOCALITY_HPP
#define DAMOV_LOCALITY_HPP

#include <cstdint>
#include <map>
#include <vector>

#include "damov/trace.hpp"

namespace damov {

struct LocalityConfig {
    uint32_t spatial_window  = 64;  // W: references per spatial window
    uint32_t temporal_window = 64;  // L: references per temporal window
    uint64_t granularity     = 1;   // address quantization (bytes) before analysis
};

struct LocalityResult {
    double   spatial_locality  = 0.0;
    double   temporal_locality = 0.0;
    uint64_t accesses          = 0;

    // Diagnostic distributions (normalized). Key = stride / reuse bin.
    std::map<uint64_t, double> stride_profile;  // Eq.1 stride_profile(i)
    std::map<uint32_t, double> reuse_profile;   // Eq.2 reuse_profile(i)
};

// Streaming analyzer: feed accesses one at a time (feed / feedAddress), then
// call finalize(). This keeps memory bounded to O(W + L) regardless of trace
// length.
class LocalityAnalyzer {
public:
    explicit LocalityAnalyzer(const LocalityConfig& cfg = {});

    void feed(const MemAccess& a) { feedAddress(a.addr); }
    void feedAddress(uint64_t addr);

    // Convenience: consume an entire trace file. Returns the result.
    LocalityResult analyzeTrace(TraceReader& reader);

    // Compute the final metrics from everything fed so far.
    LocalityResult finalize() const;

private:
    LocalityConfig cfg_;

    // Spatial state: rolling window of the last W quantized addresses.
    std::vector<uint64_t>          spatial_win_;
    size_t                         spatial_pos_ = 0;
    bool                           spatial_full_ = false;
    std::map<uint64_t, uint64_t>   stride_hist_;   // stride -> #windows
    uint64_t                       spatial_windows_ = 0;

    // Temporal state: sliding window of the last L quantized addresses with a
    // multiset-style count map for O(1) amortized reuse counting.
    std::vector<uint64_t>          temporal_win_;
    size_t                         temporal_pos_ = 0;
    bool                           temporal_full_ = false;
    std::map<uint64_t, uint32_t>   window_counts_;  // addr -> occurrences in L
    std::map<uint32_t, uint64_t>   reuse_hist_;     // floor(log2 N) -> #addresses
    uint64_t                       total_accesses_ = 0;

    void addSpatial(uint64_t qaddr);
    void addTemporal(uint64_t qaddr);
    static uint32_t floorLog2(uint32_t n);
};

}  // namespace damov

#endif  // DAMOV_LOCALITY_HPP
