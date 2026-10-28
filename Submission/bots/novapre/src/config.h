// nova: every tunable in one place, with the observation it comes from (see NewStrategy.md / Observations.md).
#pragma once
#include <cambc.h>
#include <cstdint>

namespace bc = cambc;
using bc::bitboard;
using bc::team;
using bc::vec2;

constexpr std::uint16_t UNREACH = bc::distance_field::unreachable;

inline int cheb(vec2 a, vec2 b) { return static_cast<int>(a.chebyshev_distance(b)); }

inline bitboard square(vec2 p, int r) {
    bitboard b;
    b.draw_chebyshev(p, r);
    return b;
}

// Last decision stage, printed with any turn error.
inline const char* g_stage = "";

namespace Nv {
// ---- farming (top-10: first clear r19, clusters and wolves on the own half first, ~5 clears per 100 rounds) ----
inline constexpr float GOLD_W = 0.12f;         // gold per gem of value (v65's tuned weight; 0.5 chased gold-only camps)
inline constexpr float SIDE_OWN = 1.2f;        // group nearer our spawn
inline constexpr float SIDE_MID = 1.0f;
inline constexpr float SIDE_AWAY = 0.6f;       // enemy half (1.0 while RAID_DEAD enemies are dead)
inline constexpr int RAID_DEAD = 2;
inline constexpr float OWN_RATIO = 0.8f;       // ownership: walk from our spawn < 0.8 x walk from theirs
inline constexpr float SOLO_MARGIN = 0.25f;    // keep this share of max HP after a solo camp fight
inline constexpr float JUNGLE_TAKEN = 0.7f;    // Jungle emblem: 30% less camp damage
inline constexpr int RESCORE_EVERY = 4;        // rounds between full re-scores
inline constexpr float SWITCH = 2.0f;          // a new target must beat the current one by this much
inline constexpr float CLAIMED = 0.2f;         // value share of a group an ally has claimed (small groups)
inline constexpr int HELP_WAIT = 10;           // squad wait before giving up on a group (v65 LESS_WAIT)
inline constexpr float POOL_SHARE = 0.6f;      // squad-mates rotate: each absorbs this share of max health (v65)
inline constexpr int MAX_HELPERS = 3;
inline constexpr int SKIP_AFTER_FAIL = 30;     // rounds to leave a group we could not take
inline constexpr int FIELD_FUEL = 30000;       // spare fuel needed to build one group distance field

// ---- banking (median tribute 21-26 gems, first tribute r77) ----
inline constexpr int BANK_BAG = 25;
inline constexpr int BANK_BAG_MARCELLA = 20;   // 2 gold per tributed gem
inline constexpr int BANK_NEAR = 20;           // bank a full bag only if an altar is this close...
inline constexpr int BANK_ANY = 40;            // ...or anywhere once the bag is this big
inline constexpr int DETOUR = 6;               // bank a small bag when an altar is this close
inline constexpr int DETOUR_BAG = 12;
inline constexpr int THREAT_BAG = 12;          // with an enemy within THREAT_RANGE
inline constexpr int THREAT_RANGE = 8;
inline constexpr int ALTAR_UNSAFE = 4;         // skip altars with an enemy (or memory) this close
inline constexpr int AHEAD_BAG = 15;           // bank smaller when ahead

// ---- shopping and healing (time at spawn ~5%) ----
inline constexpr int HOME_GOLD = 300;          // walk home to shop with this much gold...
inline constexpr int HOME_RANGE = 15;          // ...when spawn is this close
inline constexpr float HEAL_HP = 0.35f;        // go home to heal below this (no fight going on)
inline constexpr float HEALED_HP = 0.90f;      // stay on spawn until here
inline constexpr int RECALL_RANGE = 12;        // recall instead of walking when spawn is farther
inline constexpr float HEALTH_PER_DAMAGE = 0.5f; // Bruiser stacking: Health shards per damage shard
inline constexpr int LOCK_GOLD = 200;          // buy one altar lock after the first three emblems

// ---- fights (contact taken when ahead 57%, behind ~10%; step away at ~75% HP) ----
inline constexpr int SKIRMISH = 6;             // radius of the local fight evaluation
inline constexpr float ENGAGE = 1.25f;         // power ratio to walk into a fight
inline constexpr float TRADE = 0.8f;           // ...to keep hitting an enemy already in range
inline constexpr float DISENGAGE_HP = 0.40f;
inline constexpr float HEART_HP = 0.20f;       // Heart of Ruin: +50% damage at low HP, stays while ahead
inline constexpr float JOIN_HP = 0.60f;
inline constexpr int JOIN_RANGE = 8;
inline constexpr int FIRST_ENGAGE = 150;     // top-10 first kill r173: no walking into fights before this
inline constexpr int SPAWN_GUARD = 3;          // never chase enemies this close to their spawn (they heal there)
inline constexpr int GHOST_ROUNDS = 10;        // remember unseen enemies this long, at half weight
inline constexpr float GHOST_W = 0.5f;
inline constexpr int BEHIND = 200;             // tributed-gem gap for comeback / protect modes
inline constexpr float ENGAGE_BEHIND = 1.0f;
inline constexpr float ENGAGE_AHEAD = 1.5f;

// ---- switches under test (2026-10-28, from the nova vs v65 code review) ----
inline constexpr bool ALIVE_STATE = false;     // a visible group the engine reports alive is alive (not "away 10 rounds")
inline constexpr bool DEAD_SHOP = false;       // shop while dead (rules allow it; v65 does); claims are kept
inline constexpr bool MOVE_RESET = false;      // attack after moving (melee always, ranged via an attack reset); re-pick after a kill
inline constexpr bool MONO_AVOID = false;      // never step within reach + 1 of an awake monolith we are not farming

inline constexpr bool NEAR_SWEEP = false;     // v65: a group within NS_RANGE path steps scores x NS_MULT
inline constexpr int NS_RANGE = 4;
inline constexpr float NS_MULT = 2.0f;
inline constexpr bool MAP_MODES = false;      // v65: side weights by spawn-to-spawn walk (fight <= 35, race >= 70)
inline constexpr int MM_FIGHT_D = 35;
inline constexpr int MM_RACE_D = 70;
inline constexpr bool SQUAD_WAIT = false;     // v65 LESS_WAIT: regroup to the most-claimed squad after 4 waiting turns,
inline constexpr int SW_REGROUP = 4;          // give up after 12, and 10 rounds of score time per missing helper
inline constexpr int SW_GIVE_UP = 12;
inline constexpr int SW_SKIP = 40;
inline constexpr float SW_PENALTY = 10.f;

// ---- fight switches under test (2026-10-28) ----
inline constexpr bool JOIN_AT = false;        // judge an ally's fight around the ally, not around me
inline constexpr bool EARLY_OUT = false;      // leave when two rounds of the burst on me would kill, or below
inline constexpr float EO_HP = 0.60f;         // EO_HP in a fight that is not clearly ours (top teams step away ~77%)

// ---- vision ----
inline constexpr int WARD_EVERY = 8;
inline constexpr int WARD_NEAR = 6;            // ward within this of the target group / altar
}  // namespace Nv

// Shared memory layout (8 bytes).
namespace Mem {
inline constexpr int CLAIMS = 0;   // bytes 0..5: claimed group id + 1 per body
inline constexpr int BODIES = 6;
inline constexpr int FIGHT = 6;    // sector + 1 of a winning fight, top bit = round parity
inline constexpr int INVADE = 7;   // last round / 8 + 1 an enemy was seen on our half
}  // namespace Mem
