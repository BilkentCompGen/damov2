// damov-classify — Step 3: classify functions into the six DAMOV bottleneck
// classes from a scalability-sweep metrics table + temporal locality.
//
//   damov-classify --metrics <csv> [--locality <json|csv>]
//                  [--temporal-locality V] [--config host_ooo]
//                  [--tl-th 0.48] [--lfmr-th 0.56] [--mpki-th 11]
//                  [--ai-th 8.5] [--trend-delta 0.10] [--json|--pretty]
//
// The metrics CSV is the output of `damov-stats` (columns include
// name,config,cores,mpki,lfmr,ai). Only rows matching --config are used for the
// scalability trend. Temporal locality is taken from a locality JSON/CSV
// (matched by function name) or a single --temporal-locality value.
#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "damov/classify.hpp"

namespace {

void usage(const char* prog) {
    std::cerr << "Usage: " << prog << " --metrics <csv> [options]\n"
              << "  --metrics PATH        metrics CSV from damov-stats\n"
              << "  --locality PATH       locality JSON or CSV (name->temporal_locality)\n"
              << "  --temporal-locality V single temporal-locality value for all functions\n"
              << "  --config NAME         config rows to use for the sweep (default host_ooo)\n"
              << "  --tl-th / --lfmr-th / --mpki-th / --ai-th / --trend-delta  thresholds\n"
              << "  --json | --pretty     output format (default CSV)\n";
}

std::vector<std::string> splitCsv(const std::string& line) {
    std::vector<std::string> out;
    std::stringstream        ss(line);
    std::string              tok;
    while (std::getline(ss, tok, ',')) out.push_back(tok);
    return out;
}

// Extract a numeric JSON value for `key` from a flat JSON object string.
bool jsonNumber(const std::string& text, const std::string& key, double& out) {
    std::string k = "\"" + key + "\"";
    size_t      p = text.find(k);
    if (p == std::string::npos) return false;
    p = text.find(':', p);
    if (p == std::string::npos) return false;
    ++p;
    while (p < text.size() && (text[p] == ' ' || text[p] == '\t')) ++p;
    size_t e = p;
    while (e < text.size() && (std::isdigit(text[e]) || text[e] == '.' ||
                               text[e] == '-' || text[e] == '+' ||
                               text[e] == 'e' || text[e] == 'E'))
        ++e;
    try { out = std::stod(text.substr(p, e - p)); } catch (...) { return false; }
    return true;
}

bool jsonString(const std::string& text, const std::string& key, std::string& out) {
    std::string k = "\"" + key + "\"";
    size_t      p = text.find(k);
    if (p == std::string::npos) return false;
    p = text.find(':', p);
    if (p == std::string::npos) return false;
    p = text.find('"', p);
    if (p == std::string::npos) return false;
    size_t e = text.find('"', p + 1);
    if (e == std::string::npos) return false;
    out = text.substr(p + 1, e - p - 1);
    return true;
}

// Load temporal-locality-by-name from a locality file (JSON object or CSV with
// name + temporal_locality columns).
std::map<std::string, double> loadLocality(const std::string& path) {
    std::map<std::string, double> tl;
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open locality file: " + path);
    std::stringstream buf;
    buf << in.rdbuf();
    std::string text = buf.str();

    size_t first = text.find_first_not_of(" \t\r\n");
    if (first != std::string::npos && text[first] == '{') {
        // Single-object JSON (one function).
        std::string name = "function";
        double      v = 0;
        jsonString(text, "name", name);
        if (jsonNumber(text, "temporal_locality", v)) tl[name] = v;
        return tl;
    }

    // CSV with header.
    std::istringstream ss(text);
    std::string        header;
    if (!std::getline(ss, header)) return tl;
    std::vector<std::string> cols = splitCsv(header);
    int name_i = -1, tl_i = -1;
    for (size_t i = 0; i < cols.size(); ++i) {
        if (cols[i] == "name") name_i = (int)i;
        if (cols[i] == "temporal_locality") tl_i = (int)i;
    }
    if (name_i < 0 || tl_i < 0)
        throw std::runtime_error("locality CSV needs name & temporal_locality columns");
    std::string line;
    while (std::getline(ss, line)) {
        auto f = splitCsv(line);
        if ((int)f.size() > std::max(name_i, tl_i))
            tl[f[name_i]] = std::stod(f[tl_i]);
    }
    return tl;
}

}  // namespace

int main(int argc, char** argv) {
    std::string metrics, locality, config = "host_ooo";
    double      single_tl = -1.0;
    bool        json = false, pretty = false;
    damov::ClassifyThresholds th;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto need = [&](const char* opt) -> std::string {
            if (i + 1 >= argc) { std::cerr << "error: " << opt << " needs an argument\n"; std::exit(2); }
            return argv[++i];
        };
        if (a == "--metrics") metrics = need("--metrics");
        else if (a == "--locality") locality = need("--locality");
        else if (a == "--temporal-locality") single_tl = std::stod(need("--temporal-locality"));
        else if (a == "--config") config = need("--config");
        else if (a == "--tl-th") th.temporal_locality = std::stod(need("--tl-th"));
        else if (a == "--lfmr-th") th.lfmr = std::stod(need("--lfmr-th"));
        else if (a == "--mpki-th") th.mpki = std::stod(need("--mpki-th"));
        else if (a == "--ai-th") th.ai = std::stod(need("--ai-th"));
        else if (a == "--trend-delta") th.lfmr_trend_delta = std::stod(need("--trend-delta"));
        else if (a == "--json") json = true;
        else if (a == "--pretty") pretty = true;
        else if (a == "-h" || a == "--help") { usage(argv[0]); return 0; }
        else { std::cerr << "unknown option: " << a << "\n"; usage(argv[0]); return 2; }
    }
    if (metrics.empty()) { usage(argv[0]); return 2; }

    try {
        // Load metrics CSV, grouping scaling points by function name.
        std::ifstream in(metrics);
        if (!in) throw std::runtime_error("cannot open metrics file: " + metrics);
        std::string header;
        if (!std::getline(in, header)) throw std::runtime_error("empty metrics file");
        std::vector<std::string> cols = splitCsv(header);
        std::map<std::string, int> idx;
        for (size_t i = 0; i < cols.size(); ++i) idx[cols[i]] = (int)i;
        for (const char* req : {"name", "config", "cores", "mpki", "lfmr", "ai"})
            if (!idx.count(req))
                throw std::runtime_error(std::string("metrics CSV missing column: ") + req);

        std::map<std::string, damov::FunctionProfile> fns;
        std::vector<std::string>                      order;
        std::string                                   line;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            auto f = splitCsv(line);
            if ((int)f.size() < (int)cols.size()) continue;
            if (f[idx["config"]] != config) continue;
            const std::string& nm = f[idx["name"]];
            if (!fns.count(nm)) { fns[nm].name = nm; order.push_back(nm); }
            damov::ScalingPoint sp;
            sp.cores = std::stoi(f[idx["cores"]]);
            sp.mpki  = std::stod(f[idx["mpki"]]);
            sp.lfmr  = std::stod(f[idx["lfmr"]]);
            sp.ai    = std::stod(f[idx["ai"]]);
            fns[nm].scaling.push_back(sp);
        }

        // Attach temporal locality.
        std::map<std::string, double> tl;
        if (!locality.empty()) tl = loadLocality(locality);
        for (auto& [nm, fn] : fns) {
            if (single_tl >= 0.0) fn.temporal_locality = single_tl;
            else if (tl.count(nm)) fn.temporal_locality = tl[nm];
            else if (tl.size() == 1) fn.temporal_locality = tl.begin()->second;
        }

        // Classify and emit.
        if (!json && !pretty)
            std::cout << "name,class,bottleneck,temporal_locality,ai,mpki,lfmr,lfmr_trend,mitigation\n";

        auto trendName = [](damov::LfmrTrend t) {
            switch (t) {
                case damov::LfmrTrend::Increasing: return "increasing";
                case damov::LfmrTrend::Decreasing: return "decreasing";
                default: return "constant";
            }
        };

        bool first_json = true;
        if (json) std::cout << "[\n";
        for (const std::string& nm : order) {
            damov::Classification c = damov::classify(fns[nm], th);
            if (json) {
                std::cout << (first_json ? "  " : ",\n  ");
                first_json = false;
                std::cout << "{ \"name\": \"" << nm << "\", \"class\": \""
                          << damov::className(c.cls) << "\", \"bottleneck\": \""
                          << damov::classBottleneck(c.cls) << "\", \"temporal_locality\": "
                          << c.temporal_locality << ", \"ai\": " << c.ai << ", \"mpki\": "
                          << c.mpki << ", \"lfmr\": " << c.lfmr << ", \"lfmr_trend\": \""
                          << trendName(c.lfmr_trend) << "\", \"mitigation\": \""
                          << damov::classMitigation(c.cls) << "\" }";
            } else if (pretty) {
                std::cout << nm << "\n"
                          << "  class      : " << damov::className(c.cls) << " ("
                          << damov::classBottleneck(c.cls) << ")\n"
                          << "  metrics    : TL=" << c.temporal_locality
                          << " AI=" << c.ai << " MPKI=" << c.mpki << " LFMR=" << c.lfmr
                          << " trend=" << trendName(c.lfmr_trend) << "\n"
                          << "  mitigation : " << damov::classMitigation(c.cls) << "\n"
                          << "  rationale  : " << c.rationale << "\n\n";
            } else {
                std::cout << nm << "," << damov::className(c.cls) << ","
                          << damov::classBottleneck(c.cls) << "," << c.temporal_locality
                          << "," << c.ai << "," << c.mpki << "," << c.lfmr << ","
                          << trendName(c.lfmr_trend) << "," << damov::classMitigation(c.cls)
                          << "\n";
            }
        }
        if (json) std::cout << "\n]\n";
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
