// trace.hpp — memory-access trace reader for DAMOV2 Step-2 locality analysis.
//
// The original DAMOV modified ZSim to emit a single-thread memory trace. In
// DAMOV2 the trace comes from gem5's CommMonitor (MemTraceProbe) or from a
// simple probe; either way we consume a stream of memory references and never
// hold the whole trace in memory.
//
// Supported textual formats (auto-detected per line, '#' lines are comments):
//   1. "0x7ffed0"            -> address only          (read, size 0)
//   2. "R 0x7ffed0 8"        -> type, address, size   (R/W/r/w, decimal size)
//   3. "0x7ffed0 8"          -> address, size
// Addresses may be hex (0x-prefixed) or decimal. Gzipped files (".gz") are read
// transparently by shelling out to `gzip -dc` when zlib is unavailable.
#ifndef DAMOV_TRACE_HPP
#define DAMOV_TRACE_HPP

#include <cstdint>
#include <istream>
#include <memory>
#include <string>

namespace damov {

enum class AccessType : uint8_t { Read, Write, Unknown };

struct MemAccess {
    uint64_t   addr = 0;
    uint32_t   size = 0;
    AccessType type = AccessType::Unknown;
};

// Streaming reader over a memory-access trace. Owns its input stream.
class TraceReader {
public:
    // Opens `path`. If `path == "-"` reads from stdin. ".gz" files are
    // decompressed on the fly. Throws std::runtime_error on failure.
    explicit TraceReader(const std::string& path);
    ~TraceReader();

    TraceReader(const TraceReader&) = delete;
    TraceReader& operator=(const TraceReader&) = delete;

    // Fills `out` with the next access. Returns false at end of trace.
    bool next(MemAccess& out);

    // Number of accesses yielded so far.
    uint64_t count() const { return count_; }

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    uint64_t              count_ = 0;

    static bool parseLine(const std::string& line, MemAccess& out);
    friend struct TraceReaderTestAccess;  // exposes parseLine to unit tests
};

}  // namespace damov

#endif  // DAMOV_TRACE_HPP
