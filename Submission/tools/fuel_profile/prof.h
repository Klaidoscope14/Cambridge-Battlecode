#pragma once
// Fuel profiling harness for a Battlecode bot (profiling builds only). Include after cambc.h.
// PROF("name") at the top of a function measures inclusive fuel per call; MARK(var,"name") ... var.stop() covers a block.
// Output is parsed by parse_prof.py. Never ship a build that includes this.
#include <cambc.h>
#include <cstdint>
namespace bc = cambc;
// ---- profiling harness (kprof only) ----
namespace Prof {
inline constexpr int MAXN = 40;
inline const char* names[MAXN]; inline int n = 0;
inline unsigned long long sum[MAXN], mx[MAXN], cnt[MAXN], wrapped[MAXN];
inline int reg(const char* name) { names[n] = name; return n++; }
struct Scope {
    int id; std::uint64_t b;
    explicit Scope(int i) : id(i), b(bc::fuel_remaining()) {}
    ~Scope() {
        const std::uint64_t e = bc::fuel_remaining();
        if (e > b) { ++wrapped[id]; return; }  // fuel refilled: the turn was suspended inside
        const unsigned long long d = b - e;
        sum[id] += d; ++cnt[id]; if (d > mx[id]) mx[id] = d;
    }
};
struct Mark {
    int id; std::uint64_t b; bool on = true;
    explicit Mark(int i) : id(i), b(bc::fuel_remaining()) {}
    void stop() { if (!on) return; on = false; const std::uint64_t e = bc::fuel_remaining(); if (e > b) { ++wrapped[id]; return; } const unsigned long long d = b - e; sum[id] += d; ++cnt[id]; if (d > mx[id]) mx[id] = d; }
    ~Mark() { stop(); }
};
inline unsigned long long turns, turn_sum, turn_max, turn_over80, turn_over95, turn_wrapped;
inline unsigned long long hist[11];
}
#define MARK(var,label) static const int _pi_##var = Prof::reg(label); Prof::Mark var(_pi_##var)
#define PROF(label) static const int _pid = Prof::reg(label); Prof::Scope _ps(_pid)
