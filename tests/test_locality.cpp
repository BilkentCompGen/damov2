// Unit tests for the spatial/temporal locality metrics (Eq. 1 / Eq. 2).
#include "damov/locality.hpp"
#include "test_util.hpp"

using namespace damov;

int main() {
    // A) Perfectly sequential word accesses -> spatial locality 1.0, no reuse.
    {
        LocalityConfig cfg;
        cfg.granularity = 8;  // word granularity: consecutive words -> stride 1
        LocalityAnalyzer an(cfg);
        for (uint64_t i = 0; i < 4000; ++i) an.feedAddress(i * 8);
        LocalityResult r = an.finalize();
        CHECK_NEAR(r.spatial_locality, 1.0, 1e-9);
        CHECK_NEAR(r.temporal_locality, 0.0, 1e-9);
    }

    // B) Constant stride of 2 (byte granularity) -> min stride 2 -> spatial 0.5.
    {
        LocalityConfig cfg;
        cfg.granularity = 1;
        cfg.spatial_window = 64;
        LocalityAnalyzer an(cfg);
        for (uint64_t i = 0; i < 64 * 10; ++i) an.feedAddress(i * 2);
        LocalityResult r = an.finalize();
        CHECK_NEAR(r.spatial_locality, 0.5, 1e-9);
    }

    // C) A single address hammered repeatedly -> high reuse, no spatial stride.
    {
        LocalityConfig cfg;
        cfg.granularity = 1;
        cfg.temporal_window = 64;
        LocalityAnalyzer an(cfg);
        for (uint64_t i = 0; i < 64 * 10; ++i) an.feedAddress(0x1000);
        LocalityResult r = an.finalize();
        // Each 64-window: one address reused 63 times -> floor(log2 63)=5 ->
        // 2^5 / 64 = 0.5 (the power-of-2 binning of Eq. 2 undershoots by <=2x).
        CHECK_NEAR(r.temporal_locality, 0.5, 1e-6);
        // All addresses identical -> no distinct pair -> spatial locality 0.
        CHECK_NEAR(r.spatial_locality, 0.0, 1e-9);
    }

    // D) All-unique stream -> temporal locality 0.
    {
        LocalityConfig cfg;
        cfg.granularity = 1;
        LocalityAnalyzer an(cfg);
        for (uint64_t i = 0; i < 5000; ++i) an.feedAddress(i * 64);
        LocalityResult r = an.finalize();
        CHECK_NEAR(r.temporal_locality, 0.0, 1e-9);
    }

    // E) Metrics are bounded to [0, 1].
    {
        LocalityConfig cfg;
        LocalityAnalyzer an(cfg);
        for (uint64_t i = 0; i < 2000; ++i) an.feedAddress((i % 7) * 8);
        LocalityResult r = an.finalize();
        CHECK(r.spatial_locality >= 0.0 && r.spatial_locality <= 1.0);
        CHECK(r.temporal_locality >= 0.0 && r.temporal_locality <= 1.0);
    }

    return RUN_TESTS();
}
