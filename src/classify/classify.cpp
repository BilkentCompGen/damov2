#include "damov/classify.hpp"

#include <algorithm>
#include <sstream>

namespace damov {

const char* className(BottleneckClass c) {
    switch (c) {
        case BottleneckClass::Class1a: return "1a";
        case BottleneckClass::Class1b: return "1b";
        case BottleneckClass::Class1c: return "1c";
        case BottleneckClass::Class2a: return "2a";
        case BottleneckClass::Class2b: return "2b";
        case BottleneckClass::Class2c: return "2c";
        default: return "unknown";
    }
}

const char* classBottleneck(BottleneckClass c) {
    switch (c) {
        case BottleneckClass::Class1a: return "DRAM bandwidth";
        case BottleneckClass::Class1b: return "DRAM latency";
        case BottleneckClass::Class1c: return "L1/L2 cache capacity";
        case BottleneckClass::Class2a: return "L3 cache contention";
        case BottleneckClass::Class2b: return "L1 cache capacity";
        case BottleneckClass::Class2c: return "compute-bound";
        default: return "unknown";
    }
}

const char* classMitigation(BottleneckClass c) {
    switch (c) {
        case BottleneckClass::Class1a:
            return "NDP (exploit in-memory bandwidth; extract MLP)";
        case BottleneckClass::Class1b:
            return "NDP (lower memory latency; deep caches ineffective)";
        case BottleneckClass::Class1c:
            return "Deep cache hierarchy at high core counts (NDP only at low cores)";
        case BottleneckClass::Class2a:
            return "NDP (cheaper than enlarging L3 to fight contention)";
        case BottleneckClass::Class2b:
            return "Either host or NDP (NDP saves SRAM area at no perf penalty)";
        case BottleneckClass::Class2c:
            return "Deep cache hierarchy + hardware prefetcher (NDP degrades)";
        default:
            return "n/a";
    }
}

namespace {

// Return the scaling point with the smallest / largest core count.
const ScalingPoint* extreme(const std::vector<ScalingPoint>& s, bool want_max) {
    const ScalingPoint* best = nullptr;
    for (const auto& p : s) {
        if (!best || (want_max ? p.cores > best->cores : p.cores < best->cores))
            best = &p;
    }
    return best;
}

}  // namespace

LfmrTrend lfmrTrend(const std::vector<ScalingPoint>& scaling,
                    const ClassifyThresholds& th) {
    const ScalingPoint* lo = extreme(scaling, /*want_max=*/false);
    const ScalingPoint* hi = extreme(scaling, /*want_max=*/true);
    if (!lo || !hi || lo == hi) return LfmrTrend::Constant;
    double delta = hi->lfmr - lo->lfmr;
    if (delta >= th.lfmr_trend_delta) return LfmrTrend::Increasing;
    if (delta <= -th.lfmr_trend_delta) return LfmrTrend::Decreasing;
    return LfmrTrend::Constant;
}

Classification classify(const FunctionProfile& fn, const ClassifyThresholds& th) {
    Classification r;
    r.temporal_locality = fn.temporal_locality;
    r.lfmr_trend = lfmrTrend(fn.scaling, th);

    // Use the highest-core-count point as the representative operating point for
    // the scalar metrics (bandwidth saturation / contention manifest at scale).
    const ScalingPoint* rep = extreme(fn.scaling, /*want_max=*/true);
    if (rep) {
        r.ai   = rep->ai;
        r.mpki = rep->mpki;
        r.lfmr = rep->lfmr;
    }

    std::ostringstream why;
    const bool low_tl = fn.temporal_locality < th.temporal_locality;
    why << "temporal_locality=" << fn.temporal_locality << (low_tl ? " (LOW)" : " (HIGH)");

    if (low_tl) {
        // --- Low temporal locality: Classes 1a / 1b / 1c ---
        if (r.lfmr_trend == LfmrTrend::Decreasing) {
            r.cls = BottleneckClass::Class1c;
            why << "; LFMR decreases with cores -> caches capture locality at "
                   "scale -> 1c (L1/L2 cache capacity)";
        } else {
            // LFMR high & roughly constant: bottleneck is main memory.
            const bool high_mpki = r.mpki > th.mpki;
            why << "; LFMR high/constant; MPKI=" << r.mpki
                << (high_mpki ? " (HIGH)" : " (LOW)");
            if (high_mpki) {
                r.cls = BottleneckClass::Class1a;
                why << " -> 1a (DRAM bandwidth)";
            } else {
                r.cls = BottleneckClass::Class1b;
                why << " -> 1b (DRAM latency)";
            }
        }
    } else {
        // --- High temporal locality: Classes 2a / 2b / 2c ---
        if (r.lfmr_trend == LfmrTrend::Increasing) {
            r.cls = BottleneckClass::Class2a;
            why << "; LFMR increases with cores -> cache contention at scale -> "
                   "2a (L3 cache contention)";
        } else {
            const bool high_ai = r.ai > th.ai;
            why << "; LFMR low; AI=" << r.ai << (high_ai ? " (HIGH)" : " (LOW)");
            if (high_ai) {
                r.cls = BottleneckClass::Class2c;
                why << " -> 2c (compute-bound)";
            } else {
                r.cls = BottleneckClass::Class2b;
                why << " -> 2b (L1 cache capacity)";
            }
        }
    }

    r.rationale = why.str();
    return r;
}

}  // namespace damov
