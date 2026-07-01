#include "damov/locality.hpp"

#include <algorithm>
#include <cmath>

namespace damov {

LocalityAnalyzer::LocalityAnalyzer(const LocalityConfig& cfg) : cfg_(cfg) {
    if (cfg_.spatial_window == 0) cfg_.spatial_window = 1;
    if (cfg_.temporal_window == 0) cfg_.temporal_window = 1;
    if (cfg_.granularity == 0) cfg_.granularity = 1;
    spatial_win_.reserve(cfg_.spatial_window);
    temporal_win_.assign(cfg_.temporal_window, UINT64_MAX);
}

uint32_t LocalityAnalyzer::floorLog2(uint32_t n) {
    uint32_t r = 0;
    while (n > 1) {
        n >>= 1;
        ++r;
    }
    return r;
}

void LocalityAnalyzer::feedAddress(uint64_t addr) {
    // Quantize to the analysis granularity (paper uses word granularity).
    const uint64_t q = addr / cfg_.granularity;
    ++total_accesses_;
    addSpatial(q);
    addTemporal(q);
}

// --- Spatial (Eq. 1): tumbling windows of W; min pairwise stride per window. ---
void LocalityAnalyzer::addSpatial(uint64_t qaddr) {
    spatial_win_.push_back(qaddr);
    if (spatial_win_.size() < cfg_.spatial_window) return;

    // Window full: compute the minimum distance between any two *distinct*
    // addresses. Sorting makes this the minimum adjacent difference.
    std::sort(spatial_win_.begin(), spatial_win_.end());
    uint64_t min_stride = UINT64_MAX;
    for (size_t i = 1; i < spatial_win_.size(); ++i) {
        uint64_t d = spatial_win_[i] - spatial_win_[i - 1];
        if (d != 0 && d < min_stride) min_stride = d;
    }
    // A window of all-identical addresses has no stride; skip it rather than
    // dividing by zero. Such windows contribute nothing to spatial locality.
    if (min_stride != UINT64_MAX) {
        ++stride_hist_[min_stride];
        ++spatial_windows_;
    }
    spatial_win_.clear();
}

// --- Temporal (Eq. 2): tumbling windows of L; reuse histogram over repeats. ---
void LocalityAnalyzer::addTemporal(uint64_t qaddr) {
    ++window_counts_[qaddr];
    ++temporal_pos_;
    if (temporal_pos_ < cfg_.temporal_window) return;

    // Window full: for each address occurring c times, the number of reuses is
    // N = c - 1. Addresses touched only once (N == 0) are not reused and are
    // not counted. Bin by floor(log2 N): N==1 -> bin 0 ("reused once"),
    // N==2..3 -> bin 1 ("reused twice"), etc. (matches the paper's wording).
    for (const auto& [addr, c] : window_counts_) {
        if (c < 2) continue;
        const uint32_t reuses = c - 1;
        ++reuse_hist_[floorLog2(reuses)];
    }
    window_counts_.clear();
    temporal_pos_ = 0;
}

LocalityResult LocalityAnalyzer::finalize() const {
    LocalityResult r;
    r.accesses = total_accesses_;

    // Spatial locality: Σ stride_profile(i) / i, with stride_profile normalized
    // to a probability over completed windows.
    if (spatial_windows_ > 0) {
        double total = static_cast<double>(spatial_windows_);
        for (const auto& [stride, count] : stride_hist_) {
            double p = static_cast<double>(count) / total;
            r.stride_profile[stride] = p;
            r.spatial_locality += p / static_cast<double>(stride);
        }
    }
    // Spatial locality is by construction in [0, 1] (stride >= 1 after
    // quantization, probabilities sum to 1). Clamp against FP drift.
    if (r.spatial_locality > 1.0) r.spatial_locality = 1.0;

    // Temporal locality: Σ 2^i * reuse_profile(i) / total_accesses. Here
    // reuse_profile(i) is the raw count of reused addresses in bin i (not
    // normalized), matching the paper's Eq. 2 numerator.
    if (total_accesses_ > 0) {
        double num = 0.0;
        for (const auto& [bin, count] : reuse_hist_) {
            double weighted = std::ldexp(static_cast<double>(count), bin);  // count * 2^bin
            num += weighted;
        }
        r.temporal_locality = num / static_cast<double>(total_accesses_);

        // Normalized reuse profile for diagnostics.
        uint64_t reused_total = 0;
        for (const auto& [bin, count] : reuse_hist_) reused_total += count;
        if (reused_total > 0)
            for (const auto& [bin, count] : reuse_hist_)
                r.reuse_profile[bin] =
                    static_cast<double>(count) / static_cast<double>(reused_total);
    }
    if (r.temporal_locality > 1.0) r.temporal_locality = 1.0;

    return r;
}

LocalityResult LocalityAnalyzer::analyzeTrace(TraceReader& reader) {
    MemAccess a;
    while (reader.next(a)) feed(a);
    return finalize();
}

}  // namespace damov
