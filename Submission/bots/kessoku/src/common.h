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
inline int g_breaks = 0;      // channel breaks this game (trace counter)
inline int g_break_kind = 0;  // Channel kind of the latest break

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
// Channel breaking: worth of interrupting each enemy channel (plus bag / 50).
// Measured 2026-10-19: free hits on recallers + stuns on tributes/teleports is
// neutral-to-better (mirror 9/18, starter-python 432 -> 427 rounds, 6 -> 3 deaths);
// chasing recallers and spending spells on them cost farming (starter-cpp 423 -> 436).
inline constexpr bool BREAK_CHANNELS = true;
inline constexpr float BREAK_RECALL = 2.0f;
inline constexpr float BREAK_TRIBUTE = 3.0f;    // only bags of 10+ gems
inline constexpr float BREAK_TELEPORT = 2.5f;
inline constexpr bool BREAK_CHASE = false;          // melee steps in to hit a recaller
inline constexpr bool BREAK_RECALL_SPELLS = false;  // spend damage spells on recallers
// Ranged champions with an attack reset (Vesper Vale, Tavi, Willow): a move
// spends the attack allowance, the reset restores it (probed 2026-10-19: works).
// Off: with those three force-drafted on both sides it gained nothing (mirror
// 9/18; starter-cpp 436 -> 439 rounds; starter-python 429 -> 444 rounds and
// 2 -> 6 deaths, 9 with the chase). The reset is one extra attack per 8 turns
// whenever it is spent, so spending it on a move only shifts it.
inline constexpr bool RANGED_MOVE_RESET = false;  // move, reset, attack in one turn
inline constexpr bool RANGED_CHASE = false;       // step toward a killable enemy, then fire
inline constexpr bool TEST_FORCE_RANGED = false;  // A/B only: draft Vesper, Tavi, Willow first
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
// Capture assignment: one champion captures a finished group. Vesper Vale
// (+20% gold, +40% with Treasure) takes camps worth this much gold; otherwise the
// biggest bag can, so the reward rides an altar trip that is coming anyway.
// Measured 2026-10-19 with Vesper force-drafted on both sides: Vesper-only gives
// +12% team gold and mirror 11/18 (parity 9/18), but ~28 rounds slower vs the
// starters. The biggest-bag rule was 15-35 rounds slower everywhere -> off.
// Inert unless Vesper is drafted (the draft rarely picks her).
inline constexpr bool CAPTURE_ASSIGN = true;
inline constexpr int CAPTURE_GOLD_MIN = 60;
inline constexpr bool CAPTURE_BY_BAG = false;  // biggest bag captures when Vesper is not involved
inline constexpr int CAPTURE_RANGE = 6;  // allies this close to the group are candidates
inline constexpr bool TEST_FORCE_VESPER = false;  // A/B only: draft Vesper Vale first
// Ryth turns 1% of bonus health into strength and usually tanks camps first.
// 0 = Monster(str) -> Jungle(hp) -> Power(str) like everyone,
// 1 = Durability(hp, -10% all damage) first, 2 = Jungle(hp, -30% camp damage) first.
// Measured 2026-10-19 with Ryth force-drafted: both variants mirror 9/18 (parity)
// and within a few rounds of build 0 vs the starters, with ~25% fewer deaths
// (20 -> 14/15). Shipped 2: marginally fastest of the three.
inline constexpr int RYTH_BUILD = 2;
inline constexpr bool TEST_FORCE_RYTH = false;  // A/B only: draft Ryth first
// Prism gains 0.2 Focus per carried gem, so she carries longer when it is safe:
// a bigger bank threshold while no enemy has been seen for a while, and enemies
// nearby only force a bank when we are outmatched (she fights with the bag).
// Measured 2026-10-19 with Prism force-drafted: mirror 9/18 (parity), ~5 rounds
// faster vs the starters, deaths 20 -> 16. Inert unless the draft picks Prism.
inline constexpr bool PRISM_CARRIER = true;
inline constexpr int PRISM_BANK_BAG = 70;
inline constexpr int PRISM_SAFE_ROUNDS = 15;     // rounds since the last enemy sighting
inline constexpr bool TEST_FORCE_PRISM = false;  // A/B only: draft Prism first
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
