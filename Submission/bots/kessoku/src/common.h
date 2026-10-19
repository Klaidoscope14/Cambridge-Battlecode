// Shared helpers and tunables. Every strategic constant lives in Cfg.
#pragma once
#include <cambc.h>
#include <cstdint>
#include <vector>

namespace bc = cambc;
using bc::bitboard;
using bc::team;
using bc::vec2;

constexpr std::uint16_t UNREACH = bc::distance_field::unreachable;

inline int cheb(vec2 a, vec2 b) { return static_cast<int>(a.chebyshev_distance(b)); }

// Last decision stage, printed with any turn error to locate it.
inline const char* g_stage = "";

inline bitboard square(vec2 p, int r) {
    bitboard b;
    b.draw_chebyshev(p, r);
    return b;
}

namespace Cfg {
// Banking: go tribute once the bag is this big, or opportunistically when close.
inline constexpr int BANK_BAG = 48;
inline constexpr int BANK_NEAR_DIST = 4;
inline constexpr int BANK_THREAT_BAG = 20;  // bank early with enemies around
// Health management.
inline constexpr float RETREAT_HP = 0.30f;
inline constexpr float FIGHT_HP_MARGIN = 0.20f;  // keep this much HP after a camp fight
// Target selection.
inline constexpr float GOLD_WEIGHT = 0.12f;
inline constexpr float CLAIMED_PENALTY = 0.30f;
inline constexpr float ENEMY_NEAR_PENALTY = 0.40f;
inline constexpr float SWITCH_MARGIN = 1.30f;
inline constexpr int RETARGET_EVERY = 4;  // rounds between full target re-scores
inline constexpr float SQUAD_CLAIM_BONUS = 0.5f;  // per ally already committed to a squad target
inline constexpr int SQUAD_WAIT_RING = 5;         // wait this far from monsters (they reach 3)
inline constexpr int SQUAD_REGROUP_TURNS = 12;    // then move to the best-supported squad target
inline constexpr int SQUAD_GIVE_UP_TURNS = 40;    // then abandon the target for a while
inline constexpr float SQUAD_HEAL_FIRST = 0.75f;  // heal at spawn before waiting below this HP
// Enemy threat.
inline constexpr float LETHAL_MARGIN = 1.15f;  // retreat when visible burst * this reaches our HP
inline constexpr float DANGER_TILE = 0.60f;    // avoid tiles whose burst exceeds this share of HP
inline constexpr float OUTMATCHED = 1.25f;     // enemy fight power over ours that counts as losing
inline constexpr int SKIRMISH_RANGE = 7;       // champions this close take part in a fight
inline constexpr int THREAT_BANK_BAG = 10;     // bank this early when outmatched
inline constexpr int THREAT_BANK_RANGE = 8;
// Shopping.
inline constexpr int SHOP_TRIP_GOLD = 150;
inline constexpr int RECALL_SHOP_GOLD = 270;
inline constexpr int LOCK_MIN_GOLD = 40;
}  // namespace Cfg

// 8-byte shared memory layout.
namespace Mem {
inline constexpr int CLAIMS = 0;        // bytes 0..5: claimed group id + 1 per body
inline constexpr int MAX_BODIES = 6;
inline constexpr int CAPTURE_GROUP = 6; // group id + 1 of the latest capture
inline constexpr int CAPTURE_ROUND = 7; // low byte of that capture's round
}  // namespace Mem
