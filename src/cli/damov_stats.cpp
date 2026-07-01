// damov-stats — parse gem5 + Ramulator2 statistics into DAMOV metrics.
//
//   damov-stats --gem5 <stats.txt> [--ramulator2 <stats>] [--patterns <file>]
//               [--dump N] [--cores N] [--config NAME] [--name NAME] [--json]
//
// Emits one CSV row (or JSON object) with IPC, MPKI, LFMR, AI and the raw
// counters. Designed to be appended into a per-function metrics table that
// `damov-classify` consumes.
#include <cstdlib>
#include <iostream>
#include <string>

#include "damov/metrics.hpp"

namespace {
void usage(const char* prog) {
    std::cerr << "Usage: " << prog << " --gem5 <stats.txt> [options]\n"
              << "  --gem5 PATH         gem5 stats.txt to parse\n"
              << "  --ramulator2 PATH   Ramulator2 stats file (optional)\n"
              << "  --patterns PATH     stat-name pattern override file\n"
              << "  --dump N            which stats dump to use (-1 = last)\n"
              << "  --cores N           core count (recorded in output)\n"
              << "  --config NAME       config label, e.g. host_ooo/host_prefetch/ndp\n"
              << "  --name NAME         function name\n"
              << "  --header            also print a CSV header line\n"
              << "  --json              emit JSON instead of CSV\n";
}
}  // namespace

int main(int argc, char** argv) {
    std::string gem5, ramulator2, patterns, name = "function", config = "host_ooo";
    int         dump = -1, cores = 0;
    bool        json = false, header = false;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto need = [&](const char* opt) -> std::string {
            if (i + 1 >= argc) { std::cerr << "error: " << opt << " needs an argument\n"; std::exit(2); }
            return argv[++i];
        };
        if (a == "--gem5") gem5 = need("--gem5");
        else if (a == "--ramulator2") ramulator2 = need("--ramulator2");
        else if (a == "--patterns") patterns = need("--patterns");
        else if (a == "--dump") dump = std::stoi(need("--dump"));
        else if (a == "--cores") cores = std::stoi(need("--cores"));
        else if (a == "--config") config = need("--config");
        else if (a == "--name") name = need("--name");
        else if (a == "--json") json = true;
        else if (a == "--header") header = true;
        else if (a == "-h" || a == "--help") { usage(argv[0]); return 0; }
        else { std::cerr << "unknown option: " << a << "\n"; usage(argv[0]); return 2; }
    }
    if (gem5.empty()) { usage(argv[0]); return 2; }

    try {
        damov::StatPatterns pat =
            patterns.empty() ? damov::StatPatterns{} : damov::StatPatterns::fromFile(patterns);
        damov::RawStats raw;
        raw.loadGem5(gem5, dump);
        if (!ramulator2.empty()) raw.loadRamulator2(ramulator2);

        damov::Metrics m = damov::Metrics::compute(raw, pat);

        if (json) {
            std::cout << "{ \"name\": \"" << name << "\", \"config\": \"" << config
                      << "\", \"cores\": " << cores
                      << ", \"ipc\": " << m.ipc << ", \"mpki\": " << m.mpki
                      << ", \"lfmr\": " << m.lfmr << ", \"ai\": " << m.ai
                      << ", \"instructions\": " << m.instructions
                      << ", \"l1_misses\": " << m.l1_misses
                      << ", \"llc_misses\": " << m.llc_misses << " }\n";
        } else {
            if (header)
                std::cout << "name,config,cores,ipc,mpki,lfmr,ai,instructions,l1_misses,llc_misses\n";
            std::cout << name << "," << config << "," << cores << "," << m.ipc << ","
                      << m.mpki << "," << m.lfmr << "," << m.ai << "," << m.instructions
                      << "," << m.l1_misses << "," << m.llc_misses << "\n";
        }
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
