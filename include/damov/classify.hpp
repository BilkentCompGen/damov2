// classify.hpp — DAMOV Step 3 bottleneck classification (Fig. 26 decision tree).
//
// Given a function's temporal locality (from Step 2) and its architecture-
// dependent metrics (AI, MPKI, LFMR) measured across a core-count sweep, assign
// one of the six memory-bottleneck classes and recommend a mitigation.
//
//   Temporal Locality
//   ├── LOW ─────> LFMR
//   │              ├── HIGH & ~constant ─> MPKI HIGH -> 1a  DRAM bandwidth
//   │              │                       MPKI LOW  -> 1b  DRAM latency
//   │              └── DECREASING w/ cores ---------> 1c  L1/L2 cache capacity
//   └── HIGH ────> LFMR
//                  ├── INCREASING w/ cores ---------> 2a  L3 cache contention
//                  └── LOW ─────> AI HIGH -> 2c  compute-bound
//                                 AI LOW  -> 2b  L1 cache capacity
//
// Validated thresholds (paper §3.5.1): temporal locality 0.48, LFMR 0.56,
// MPKI 11.0, AI 8.5. The LFMR trend (increasing/decreasing/constant) is derived
// from LFMR values across the core-count sweep.
#ifndef DAMOV_CLASSIFY_HPP
#define DAMOV_CLASSIFY_HPP

#include <string>
#include <vector>

namespace damov {

enum class BottleneckClass {
    Class1a,  // DRAM bandwidth
    Class1b,  // DRAM latency
    Class1c,  // L1/L2 cache capacity
    Class2a,  // L3 cache contention
    Class2b,  // L1 cache capacity
    Class2c,  // compute-bound
    Unknown
};

const char* className(BottleneckClass c);        // "1a" ...
const char* classBottleneck(BottleneckClass c);  // "DRAM bandwidth" ...
const char* classMitigation(BottleneckClass c);  // recommended mitigation

// One measurement point of the scalability sweep, on the host_ooo configuration.
struct ScalingPoint {
    int    cores = 0;
    double ai    = 0;
    double mpki  = 0;
    double lfmr  = 0;
};

struct ClassifyThresholds {
    double temporal_locality = 0.48;
    double lfmr              = 0.56;
    double mpki             = 11.0;
    double ai               = 8.5;
    // Minimum absolute change in LFMR from the lowest to highest core count for
    // the trend to count as "increasing"/"decreasing" rather than "constant".
    double lfmr_trend_delta = 0.10;
};

enum class LfmrTrend { Increasing, Decreasing, Constant };

struct FunctionProfile {
    std::string               name;
    double                    temporal_locality = 0.0;  // from Step 2
    std::vector<ScalingPoint> scaling;                   // host_ooo sweep, any order
};

struct Classification {
    BottleneckClass cls = BottleneckClass::Unknown;
    LfmrTrend       lfmr_trend = LfmrTrend::Constant;
    // Representative metric values used for the decision (typically at the
    // highest core count), for transparency.
    double          temporal_locality = 0;
    double          ai   = 0;
    double          mpki = 0;
    double          lfmr = 0;
    std::string     rationale;  // human-readable explanation of the path taken
};

LfmrTrend      lfmrTrend(const std::vector<ScalingPoint>& scaling,
                         const ClassifyThresholds& th);
Classification classify(const FunctionProfile& fn,
                        const ClassifyThresholds& th = {});

}  // namespace damov

#endif  // DAMOV_CLASSIFY_HPP
