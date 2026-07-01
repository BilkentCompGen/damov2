// Unit tests for the six-class bottleneck decision tree (Fig. 26).
#include "damov/classify.hpp"
#include "test_util.hpp"

using namespace damov;

static FunctionProfile make(double tl, std::vector<ScalingPoint> pts) {
    FunctionProfile f;
    f.temporal_locality = tl;
    f.scaling = std::move(pts);
    return f;
}

int main() {
    ClassifyThresholds th;  // defaults: TL 0.48, LFMR 0.56, MPKI 11, AI 8.5

    // 1a: low TL, high & constant LFMR, high MPKI, low AI -> DRAM bandwidth.
    {
        auto f = make(0.05, {{1, 1.0, 30, 0.98}, {256, 1.0, 40, 0.97}});
        CHECK(classify(f, th).cls == BottleneckClass::Class1a);
    }
    // 1b: low TL, high & constant LFMR, low MPKI, low AI -> DRAM latency.
    {
        auto f = make(0.10, {{1, 0.5, 2, 0.95}, {256, 0.5, 3, 0.94}});
        CHECK(classify(f, th).cls == BottleneckClass::Class1b);
    }
    // 1c: low TL, LFMR decreasing with cores -> L1/L2 cache capacity.
    {
        auto f = make(0.30, {{1, 0.5, 4, 0.90}, {256, 0.5, 3, 0.09}});
        auto c = classify(f, th);
        CHECK(c.lfmr_trend == LfmrTrend::Decreasing);
        CHECK(c.cls == BottleneckClass::Class1c);
    }
    // 2a: high TL, LFMR increasing with cores -> L3 cache contention.
    {
        auto f = make(0.65, {{1, 0.5, 1, 0.03}, {256, 0.5, 5, 0.97}});
        auto c = classify(f, th);
        CHECK(c.lfmr_trend == LfmrTrend::Increasing);
        CHECK(c.cls == BottleneckClass::Class2a);
    }
    // 2b: high TL, low & constant LFMR, low AI -> L1 cache capacity.
    {
        auto f = make(0.60, {{1, 0.5, 2, 0.20}, {256, 0.5, 2, 0.20}});
        auto c = classify(f, th);
        CHECK(c.lfmr_trend == LfmrTrend::Constant);
        CHECK(c.cls == BottleneckClass::Class2b);
    }
    // 2c: high TL, low LFMR, high AI -> compute-bound.
    {
        auto f = make(0.70, {{1, 12.0, 1, 0.10}, {256, 12.0, 1, 0.10}});
        CHECK(classify(f, th).cls == BottleneckClass::Class2c);
    }

    // Trend detection honors the delta threshold (small wobble = constant).
    {
        std::vector<ScalingPoint> s = {{1, 0, 0, 0.50}, {256, 0, 0, 0.55}};
        CHECK(lfmrTrend(s, th) == LfmrTrend::Constant);
    }

    return RUN_TESTS();
}
