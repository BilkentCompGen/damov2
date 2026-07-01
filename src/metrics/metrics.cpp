#include "damov/metrics.hpp"

#include <algorithm>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace damov {

namespace {

bool contains(const std::string& hay, const std::string& needle) {
    return hay.find(needle) != std::string::npos;
}

// Parse a numeric token; returns false if not a finite number.
bool parseNumber(const std::string& tok, double& out) {
    try {
        size_t idx = 0;
        out = std::stod(tok, &idx);
        return idx == tok.size();
    } catch (const std::exception&) {
        return false;
    }
}

}  // namespace

void RawStats::loadGem5(const std::string& path, int dump_index) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open gem5 stats file: " + path);

    // Split into dumps delimited by the gem5 begin/end markers.
    std::vector<std::vector<std::string>> dumps;
    std::vector<std::string>              current;
    bool                                  in_dump = false;
    std::string                           line;
    while (std::getline(in, line)) {
        if (contains(line, "Begin Simulation Statistics")) {
            in_dump = true;
            current.clear();
            continue;
        }
        if (contains(line, "End Simulation Statistics")) {
            in_dump = false;
            dumps.push_back(std::move(current));
            current.clear();
            continue;
        }
        if (in_dump) current.push_back(line);
    }
    // Tolerate files with no explicit markers (single implicit dump).
    if (dumps.empty() && !current.empty()) dumps.push_back(std::move(current));
    if (dumps.empty()) return;

    size_t sel = dump_index < 0 ? dumps.size() - 1
                                : std::min<size_t>(dump_index, dumps.size() - 1);

    for (const std::string& l : dumps[sel]) {
        std::istringstream ss(l);
        std::string        name, value;
        if (!(ss >> name >> value)) continue;
        if (name.empty() || name[0] == '#') continue;
        double v;
        if (parseNumber(value, v)) values_[name] = v;
    }
}

void RawStats::loadRamulator2(const std::string& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open Ramulator2 stats file: " + path);
    std::string line;
    while (std::getline(in, line)) {
        // Accept "key: value" (YAML) or "key value".
        for (char& c : line)
            if (c == ':') c = ' ';
        std::istringstream ss(line);
        std::string        name, value;
        if (!(ss >> name >> value)) continue;
        if (name.empty() || name[0] == '#') continue;
        double v;
        if (parseNumber(value, v)) values_["ramulator2." + name] = v;
    }
}

double RawStats::sumMatching(const std::vector<std::string>& patterns) const {
    double sum = 0.0;
    for (const auto& [name, value] : values_)
        for (const auto& p : patterns)
            if (contains(name, p)) {
                sum += value;
                break;  // count each stat at most once
            }
    return sum;
}

double RawStats::maxMatching(const std::vector<std::string>& patterns) const {
    double best = 0.0;
    bool   any  = false;
    for (const auto& [name, value] : values_)
        for (const auto& p : patterns)
            if (contains(name, p)) {
                if (!any || value > best) best = value;
                any = true;
                break;
            }
    return best;
}

bool RawStats::has(const std::string& substr) const {
    for (const auto& [name, value] : values_)
        if (contains(name, substr)) return true;
    return false;
}

StatPatterns StatPatterns::fromFile(const std::string& path) {
    StatPatterns p;
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open stat-pattern file: " + path);

    auto split = [](const std::string& s) {
        std::vector<std::string> out;
        std::stringstream        ss(s);
        std::string              tok;
        while (std::getline(ss, tok, ',')) {
            size_t a = tok.find_first_not_of(" \t");
            size_t b = tok.find_last_not_of(" \t");
            if (a != std::string::npos) out.push_back(tok.substr(a, b - a + 1));
        }
        return out;
    };

    std::string line;
    while (std::getline(in, line)) {
        size_t hash = line.find('#');
        if (hash != std::string::npos) line = line.substr(0, hash);
        size_t eq = line.find('=');
        if (eq == std::string::npos) continue;
        std::string key = line.substr(0, eq);
        std::string val = line.substr(eq + 1);
        key.erase(std::remove_if(key.begin(), key.end(), ::isspace), key.end());
        std::vector<std::string> vals = split(val);
        if (vals.empty()) continue;

        if (key == "instructions") p.instructions = vals;
        else if (key == "cycles") p.cycles = vals;
        else if (key == "l1d_misses") p.l1d_misses = vals;
        else if (key == "l1i_misses") p.l1i_misses = vals;
        else if (key == "l1d_accesses") p.l1d_accesses = vals;
        else if (key == "llc_misses") p.llc_misses = vals;
        else if (key == "alu_ops") p.alu_ops = vals;
        else if (key == "fp_ops") p.fp_ops = vals;
        else if (key == "dram_bw") p.dram_bw = vals;
        else if (key == "dram_reads") p.dram_reads = vals;
        else if (key == "dram_writes") p.dram_writes = vals;
    }
    return p;
}

Metrics Metrics::compute(const RawStats& raw, const StatPatterns& p) {
    Metrics m;
    m.instructions = raw.sumMatching(p.instructions);
    m.cycles       = raw.maxMatching(p.cycles);
    m.l1_misses    = raw.sumMatching(p.l1d_misses) + raw.sumMatching(p.l1i_misses);
    m.llc_misses   = raw.sumMatching(p.llc_misses);
    m.l1d_accesses = raw.sumMatching(p.l1d_accesses);
    m.arith_ops    = raw.sumMatching(p.alu_ops) + raw.sumMatching(p.fp_ops);
    m.dram_reads   = raw.sumMatching(p.dram_reads);
    m.dram_writes  = raw.sumMatching(p.dram_writes);

    if (m.cycles > 0) m.ipc = m.instructions / m.cycles;
    if (m.instructions > 0) m.mpki = m.llc_misses / (m.instructions / 1000.0);
    if (m.l1_misses > 0) m.lfmr = m.llc_misses / m.l1_misses;
    if (m.l1d_accesses > 0) m.ai = m.arith_ops / m.l1d_accesses;
    return m;
}

}  // namespace damov
