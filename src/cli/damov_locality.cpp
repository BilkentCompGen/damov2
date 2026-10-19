// damov-locality — Step 2: compute architecture-independent spatial & temporal
// locality from a memory-access trace.
//
//   damov-locality --trace <file|-> [--spatial-window W] [--temporal-window L]
//                  [--granularity BYTES] [--json] [--profiles]
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

#include "damov/locality.hpp"
#include "damov/trace.hpp"

namespace {

void usage(const char* prog) {
    std::cerr
        << "Usage: " << prog << " --trace <file|-> [options]\n"
        << "  --trace PATH           memory trace (.gz supported; '-' = stdin)\n"
        << "  --spatial-window W     spatial window size (default 64)\n"
        << "  --temporal-window L    temporal window size (default 64)\n"
        << "  --granularity B        address granularity in bytes (default 8 = word)\n"
        << "  --name NAME            function name to tag output with\n"
        << "  --json                 emit JSON (default CSV)\n"
        << "  --profiles             include stride/reuse distributions (JSON)\n";
}

}  // namespace

int main(int argc, char** argv) {
    std::string          trace, name = "function";
    damov::LocalityConfig cfg;
    // The library defaults to byte granularity; the DAMOV methodology analyzes
    // at word granularity (docs/methodology.md), so that is this tool's default.
    cfg.granularity = 8;
    bool                  json = false, profiles = false;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto need = [&](const char* opt) -> std::string {
            if (i + 1 >= argc) {
                std::cerr << "error: " << opt << " needs an argument\n";
                std::exit(2);
            }
            return argv[++i];
        };
        if (a == "--trace") trace = need("--trace");
        else if (a == "--spatial-window") cfg.spatial_window = std::stoul(need("--spatial-window"));
        else if (a == "--temporal-window") cfg.temporal_window = std::stoul(need("--temporal-window"));
        else if (a == "--granularity") cfg.granularity = std::stoull(need("--granularity"));
        else if (a == "--name") name = need("--name");
        else if (a == "--json") json = true;
        else if (a == "--profiles") profiles = true;
        else if (a == "-h" || a == "--help") { usage(argv[0]); return 0; }
        else { std::cerr << "unknown option: " << a << "\n"; usage(argv[0]); return 2; }
    }
    if (trace.empty()) { usage(argv[0]); return 2; }

    try {
        damov::TraceReader     reader(trace);
        damov::LocalityAnalyzer an(cfg);
        damov::LocalityResult   res = an.analyzeTrace(reader);

        if (json) {
            std::cout << "{\n";
            std::cout << "  \"name\": \"" << name << "\",\n";
            std::cout << "  \"accesses\": " << res.accesses << ",\n";
            std::cout << "  \"spatial_locality\": " << res.spatial_locality << ",\n";
            std::cout << "  \"temporal_locality\": " << res.temporal_locality;
            if (profiles) {
                std::cout << ",\n  \"stride_profile\": {";
                bool first = true;
                for (const auto& [k, v] : res.stride_profile) {
                    std::cout << (first ? "" : ", ") << "\"" << k << "\": " << v;
                    first = false;
                }
                std::cout << "},\n  \"reuse_profile\": {";
                first = true;
                for (const auto& [k, v] : res.reuse_profile) {
                    std::cout << (first ? "" : ", ") << "\"" << k << "\": " << v;
                    first = false;
                }
                std::cout << "}";
            }
            std::cout << "\n}\n";
        } else {
            std::cout << "name,accesses,spatial_locality,temporal_locality\n";
            std::cout << name << "," << res.accesses << "," << res.spatial_locality
                      << "," << res.temporal_locality << "\n";
        }
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
