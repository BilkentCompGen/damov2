// Unit tests for parsing gem5/Ramulator2 stats and deriving DAMOV metrics.
#include <cstdio>
#include <fstream>
#include <string>

#include "damov/metrics.hpp"
#include "test_util.hpp"

using namespace damov;

static std::string writeTemp(const std::string& name, const std::string& body) {
    std::string path = std::string(".") + "/" + name;
    std::ofstream out(path);
    out << body;
    out.close();
    return path;
}

int main() {
    // A minimal but realistic gem5 stats.txt with two dumps; the last one is
    // the region of interest we want.
    const std::string gem5 =
        "---------- Begin Simulation Statistics ----------\n"
        "simInsts 1000 # committed insts (warmup)\n"
        "system.cpu.numCycles 2000 # cycles\n"
        "---------- End Simulation Statistics ----------\n"
        "---------- Begin Simulation Statistics ----------\n"
        "simInsts 1000000 # committed instructions\n"
        "system.cpu.numCycles 500000 # cpu cycles\n"
        "system.cpu.dcache.overallMisses::total 20000 # L1D misses\n"
        "system.cpu.icache.overallMisses::total 0 # L1I misses\n"
        "system.cpu.dcache.overallAccesses::total 400000 # L1D accesses\n"
        "system.l3.overallMisses::total 15000 # LLC misses\n"
        "system.cpu.commitStats0.committedInstType::IntAlu 200000 # alu\n"
        "---------- End Simulation Statistics ----------\n";

    std::string gpath = writeTemp("damov_test_gem5_stats.txt", gem5);

    RawStats raw;
    raw.loadGem5(gpath, -1);  // last dump
    Metrics m = Metrics::compute(raw);

    // IPC = 1e6 / 5e5 = 2.0
    CHECK_NEAR(m.ipc, 2.0, 1e-9);
    // MPKI = 15000 / (1e6/1000) = 15.0
    CHECK_NEAR(m.mpki, 15.0, 1e-9);
    // LFMR = 15000 / (20000 + 0) = 0.75
    CHECK_NEAR(m.lfmr, 0.75, 1e-9);
    // AI = 200000 alu / 400000 accesses = 0.5
    CHECK_NEAR(m.ai, 0.5, 1e-9);

    // The first (warmup) dump should give different instruction count.
    RawStats warm;
    warm.loadGem5(gpath, 0);
    Metrics wm = Metrics::compute(warm);
    CHECK_NEAR(wm.instructions, 1000.0, 1e-9);

    // Ramulator2 stats parse (YAML-ish).
    const std::string ram =
        "read_requests: 12345\n"
        "write_requests: 6789\n";
    std::string rpath = writeTemp("damov_test_ram_stats.yaml", ram);
    RawStats raw2;
    raw2.loadGem5(gpath, -1);
    raw2.loadRamulator2(rpath);
    Metrics m2 = Metrics::compute(raw2);
    CHECK_NEAR(m2.dram_reads, 12345.0, 1e-9);
    CHECK_NEAR(m2.dram_writes, 6789.0, 1e-9);

    std::remove(gpath.c_str());
    std::remove(rpath.c_str());
    return RUN_TESTS();
}
