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
// Emblems: Monster = +10% camp damage, Jungle = -30% camp damage taken,
// Home = recall 5 -> 3 turn ends. HOME_SLOT is Home's place in the build (-1 skips it).
// Measured 2026-10-19 (mirror vs previous build, 18 games): Monster bonus in the
// damage estimate 10/18; also counting Jungle (0.70) made fights riskier (0 -> 8
// deaths vs starter-cpp); Home after Monster 7/18, after Jungle 6/18 - this bot
// rarely recalls, so the 150 gold is worth more as stats.
inline constexpr float MONSTER_BONUS = 1.10f;
inline constexpr float JUNGLE_TAKEN = 1.00f;
inline constexpr int HOME_SLOT = -1;
// Monoliths: the monolith hits the nearest champion and hurt champions step out,
// so a squad pools its health. Each body spends this share before rotating out.
// Off: with 4-5 of 6 bodies needed, gathering stalls the economy (monolith map
// 586 vs 1018) and monoliths regenerate after aborted attempts. Worth revisiting
// for long ladder games where regular camps run dry.
inline constexpr bool MONOLITH_FIGHTS = false;
inline constexpr float MONOLITH_POOL_SHARE = 0.60f;
inline constexpr int MONOLITH_MAX_BAG = 10;  // bank before joining a monolith fight
inline constexpr int MONOLITH_MAX_NEED = 2;  // never tie up more helpers than this (monoliths regenerate)
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
