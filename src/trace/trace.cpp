#include "damov/trace.hpp"

#include <cctype>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace damov {

namespace {

// Parse an unsigned integer that may be hex (0x...) or decimal. Returns false
// if `tok` is not a valid number.
bool parseUint(const std::string& tok, uint64_t& value) {
    if (tok.empty()) return false;
    size_t idx = 0;
    int    base = 10;
    if (tok.size() > 2 && tok[0] == '0' && (tok[1] == 'x' || tok[1] == 'X'))
        base = 16;
    try {
        value = std::stoull(tok, &idx, base);
    } catch (const std::exception&) {
        return false;
    }
    return idx == tok.size();
}

AccessType parseType(const std::string& tok) {
    if (tok.size() != 1) return AccessType::Unknown;
    switch (tok[0]) {
        case 'R': case 'r': case 'L': case 'l': return AccessType::Read;
        case 'W': case 'w': case 'S': case 's': return AccessType::Write;
        default: return AccessType::Unknown;
    }
}

}  // namespace

// A pimpl that owns either an ifstream, a piped FILE* (for .gz), or points at
// std::cin.
struct TraceReader::Impl {
    std::istream*                in = nullptr;
    std::ifstream                file;
    FILE*                        pipe = nullptr;
    std::unique_ptr<std::istream> pipe_stream;  // wraps the piped data
    std::string                  pipe_buffer;
};

TraceReader::TraceReader(const std::string& path)
    : impl_(std::make_unique<Impl>()) {
    if (path == "-") {
        impl_->in = &std::cin;
        return;
    }

    const bool gz = path.size() > 3 && path.compare(path.size() - 3, 3, ".gz") == 0;
    if (gz) {
        // Decompress via `gzip -dc` and slurp into a buffer-backed stream. This
        // avoids a hard zlib dependency while still supporting the compressed
        // traces gem5's CommMonitor typically produces.
        std::string cmd = "gzip -dc '" + path + "'";
        impl_->pipe = popen(cmd.c_str(), "r");
        if (!impl_->pipe)
            throw std::runtime_error("failed to open gzip pipe for: " + path);
        std::string data;
        char        buf[1 << 16];
        size_t      n;
        while ((n = fread(buf, 1, sizeof(buf), impl_->pipe)) > 0)
            data.append(buf, n);
        impl_->pipe_buffer = std::move(data);
        impl_->pipe_stream =
            std::make_unique<std::istringstream>(impl_->pipe_buffer);
        impl_->in = impl_->pipe_stream.get();
        return;
    }

    impl_->file.open(path);
    if (!impl_->file)
        throw std::runtime_error("failed to open trace file: " + path);
    impl_->in = &impl_->file;
}

TraceReader::~TraceReader() {
    if (impl_ && impl_->pipe) pclose(impl_->pipe);
}

bool TraceReader::parseLine(const std::string& line, MemAccess& out) {
    // Tokenize on whitespace.
    std::string tokens[3];
    int         ntok = 0;
    std::istringstream ss(line);
    for (; ntok < 3 && (ss >> tokens[ntok]); ++ntok) {
    }
    if (ntok == 0) return false;

    out = MemAccess{};

    if (ntok == 1) {
        // "addr"
        return parseUint(tokens[0], out.addr);
    }

    // First token may be an access type or the address.
    AccessType t = parseType(tokens[0]);
    if (t != AccessType::Unknown) {
        // "type addr [size]"
        out.type = t;
        if (!parseUint(tokens[1], out.addr)) return false;
        if (ntok >= 3) {
            uint64_t sz = 0;
            if (parseUint(tokens[2], sz)) out.size = static_cast<uint32_t>(sz);
        }
        return true;
    }

    // "addr size"
    if (!parseUint(tokens[0], out.addr)) return false;
    uint64_t sz = 0;
    if (parseUint(tokens[1], sz)) out.size = static_cast<uint32_t>(sz);
    return true;
}

bool TraceReader::next(MemAccess& out) {
    std::string line;
    while (std::getline(*impl_->in, line)) {
        // Skip blank/comment lines.
        size_t first = line.find_first_not_of(" \t\r\n");
        if (first == std::string::npos || line[first] == '#') continue;
        if (parseLine(line, out)) {
            ++count_;
            return true;
        }
        // Silently skip malformed lines; robustness matters more than being
        // strict when consuming multi-GB simulator traces.
    }
    return false;
}

}  // namespace damov
