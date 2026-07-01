// metrics.hpp — derive DAMOV architecture-dependent metrics from simulator
// statistics (Step 3 inputs).
//
// The three metrics that drive the bottleneck classification (Section 2.4.1):
//   AI   — Arithmetic Intensity: arithmetic/logic ops per L1 cache line accessed
//   MPKI — Last-Level-Cache Misses Per Kilo-Instruction
//   LFMR — Last-to-First Miss Ratio: LLC misses / total L1 misses
// plus IPC and (when available) Ramulator2 DRAM bandwidth/latency for reporting.
//
// gem5 stat names differ across versions and configurations, so the mapping
// from raw stats to quantities is expressed as configurable substring patterns
// (StatPatterns) with sensible defaults for a modern gem5 classic-cache system.
#ifndef DAMOV_METRICS_HPP
#define DAMOV_METRICS_HPP

#include <map>
#include <string>
#include <vector>

namespace damov {

// Raw "name -> value" pairs parsed from a gem5 stats.txt and/or a Ramulator2
// stats file.
class RawStats {
public:
    // Parse a gem5 stats.txt. If the file contains multiple dumps (separated by
    // "---------- Begin/End Simulation Statistics ----------"), `dump_index`
    // selects which one (-1 = last). Accumulates into this object.
    void loadGem5(const std::string& path, int dump_index = -1);

    // Parse a Ramulator2 stats file (YAML-ish "key: value" or "key value").
    // Keys are prefixed with "ramulator2." to avoid collisions.
    void loadRamulator2(const std::string& path);

    // Sum the values of every stat whose name contains ANY of `patterns`.
    double sumMatching(const std::vector<std::string>& patterns) const;
    // Maximum value among stats whose name contains ANY of `patterns`.
    double maxMatching(const std::vector<std::string>& patterns) const;

    bool   has(const std::string& substr) const;
    size_t size() const { return values_.size(); }

private:
    std::map<std::string, double> values_;
};

// Configurable substring patterns mapping raw stats to DAMOV quantities.
struct StatPatterns {
    std::vector<std::string> instructions = {"simInsts", "committedInsts"};
    std::vector<std::string> cycles       = {"numCycles"};
    std::vector<std::string> l1d_misses   = {"dcache.overallMisses::total",
                                             "dcache.demandMisses::total"};
    std::vector<std::string> l1i_misses   = {"icache.overallMisses::total",
                                             "icache.demandMisses::total"};
    std::vector<std::string> l1d_accesses = {"dcache.overallAccesses::total",
                                             "dcache.demandAccesses::total"};
    std::vector<std::string> llc_misses   = {"l3.overallMisses::total",
                                             "l3.demandMisses::total",
                                             "llc.overallMisses::total"};
    std::vector<std::string> alu_ops      = {"num_int_alu_accesses",
                                             "statIssuedInstType_0::IntAlu",
                                             "committedInstType::IntAlu"};
    std::vector<std::string> fp_ops       = {"num_fp_alu_accesses",
                                             "committedInstType::FloatAdd",
                                             "committedInstType::FloatMult"};
    // Ramulator2 (ramulator_stats.yaml) controller counters, flattened and
    // prefixed with "ramulator2." by RawStats::loadRamulator2.
    std::vector<std::string> dram_bw      = {"avg_read_latency"};
    std::vector<std::string> dram_reads   = {"num_read_reqs", "read_requests", "reads"};
    std::vector<std::string> dram_writes  = {"num_write_reqs", "write_requests", "writes"};

    // Load pattern overrides from a "key = a,b,c" text file (keys match the
    // field names above). Lines starting with '#' are comments.
    static StatPatterns fromFile(const std::string& path);
};

struct Metrics {
    double instructions = 0;
    double cycles       = 0;
    double l1_misses    = 0;
    double llc_misses   = 0;
    double l1d_accesses = 0;
    double arith_ops    = 0;
    double dram_reads   = 0;
    double dram_writes  = 0;

    // Derived DAMOV metrics.
    double ipc  = 0;
    double mpki = 0;   // LLC misses per kilo-instruction
    double lfmr = 0;   // LLC misses / L1 misses
    double ai   = 0;   // arithmetic ops per L1 access

    // Compute derived metrics from a RawStats object using `patterns`.
    static Metrics compute(const RawStats& raw, const StatPatterns& patterns = {});
};

}  // namespace damov

#endif  // DAMOV_METRICS_HPP
