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
inline int g_handoffs = 0;     // aggro handoff steps this game (trace counter)
inline int g_ghost_turns = 0;  // turns a bag carrier steered by ghosts (trace counter)

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
// Fuel (100x100 maps ran out mid-turn ~300 times a game on 01big_world): skip a re-score or
// the detour field when this turn cannot afford it, cache the detour field per target, and
// optionally re-score less often on big maps.
// Measured v20 vs v19 (21 maps): cache only 21/42, 9-map fuel events 728 -> 263 (big_world
// 467 -> 38); + guard 20/42, events 150; + re-score every 8 on big maps 18/42.
inline constexpr bool FUEL_GUARD = false;
// Cassi & Issac (review F4): one death kills both halves and pays out both bags; on the
// ladder the pair took 52% of our body-deaths.
// Measured v21 vs v20 (21 maps): retreat 0.50 26/42, deaths vs old bot 94 -> 80 (pair 0.69 -> 0.57
// per game), zlock2 13/16; 0.45 23/42, 0.40 21/42, 0.45 + min-HP 22/42; min-HP alone 21/42;
// together x1.5 22/42; draft score 8.1 drops the pick entirely: 15/42.
inline constexpr float PAIR_RETREAT_HP = 0.50f;      // retreat threshold for each half (RETREAT_HP otherwise)
// Review F6: melee champions walk at a ranged poker within POKER_RANGE when allies are close and
// our side is stronger. F7d: also retreat when health < BURST_RETREAT_MULT x the damage aimed at
// us this turn (enemy burst + awake camps within 3); 0 disables.
// Measured v22 vs v21: chase 25/42 (deaths 212 vs 265), vs the ranged-poker bot zpoke 22 -> 28/42;
// burst retreat 1.0/1.5: 24/23 of 42, more deaths vs the old bot (80 -> 93/95) -> off.
inline constexpr bool MELEE_CHASE_POKERS = true;
inline constexpr int POKER_RANGE = 4;
inline constexpr float BURST_RETREAT_MULT = 0.f;
inline constexpr bool PAIR_MIN_HP = false;           // retreat on the lower of the two halves' health
inline constexpr float PAIR_TOGETHER_BONUS = 1.0f;   // score bonus for the group the other half claims
inline constexpr float PAIR_DRAFT_SCORE = 9.6f;      // draft value of the pick
inline constexpr float HOR_DRAFT_SCORE = 10.0f;       // Heart of Ruin (added in cambc 3.0)
inline constexpr bool DASH_STRIKE = true;   // aim dashes that have a landing effect at enemies/camps
inline constexpr int DASH_STRIKE_CAMPS = 2;   // camps the landing must catch to be worth the cooldown
inline constexpr int FUEL_RESCORE_MIN = 60000;  // a 100x100 re-score costs ~45K
inline constexpr int FUEL_DETOUR_MIN = 40000;   // a 100x100 detour field costs ~27K
inline constexpr bool DETOUR_CACHE = true;
inline constexpr int BIG_MAP_AREA = 6400;       // 80x80 and up
inline constexpr int RETARGET_EVERY_BIG = 4;
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
inline constexpr int LOSING_RANGE = 4;         // outmatched with an enemy this close: disengage (5: 18/42, 6: 15/42 vs v17)
// Feeding fixes (v18), measured vs v17 on 21 maps: safe recall 22/42 (deaths 326 -> 285);
// with death-avoid (range 4, 150 rounds) 23/42, deaths 251, vs starter-cpp deaths 90 -> 53.
inline constexpr bool SAFE_RECALL = true;      // hurt since last turn: walk home rather than recall
inline constexpr bool DEATH_AVOID = true;      // after dying, skip the groups near where we fell
inline constexpr int DEATH_AVOID_RANGE = 4;   // 6: 21/42
inline constexpr int DEATH_AVOID_ROUNDS = 150;  // includes the 60-turn respawn (80/250 at range 6: 23/24 of 42)
// Hostile-review fixes (HostileReview.md, 2026-10-20). F1: altar siege flip-flop - an altar
// with an enemy seen near it stays threatened for ALTAR_HOT_ROUNDS (ghosts expire in 8, so
// carriers turned back and forth between two camped altars); heal at CALM_HEAL_HP when nothing
// is near (champions idled at 31-35% HP); no banking for ESCAPE_BANK_EMBARGO rounds after
// escaping with a bag. F2: walk up and break enemy altar locks (3 basic attacks).
// F3: only reachable altars count as a safe alternative (collision's second altar is walled off).
// F7a: a dead champion clears its claim byte. F7b: a gold/gem jump only counts as a capture
// on the group we were holding (a kill bounty on a camp tile used to broadcast a capture).
inline constexpr int ALTAR_HOT_ROUNDS = 60;
inline constexpr float CALM_HEAL_HP = 0.50f;
inline constexpr int ESCAPE_BANK_EMBARGO = 20;
inline constexpr bool CLEAR_ENEMY_LOCKS = true;
inline constexpr bool REACHABLE_ANY_SAFE = true;
inline constexpr bool DEAD_CLEARS_CLAIM = false;  // measured: our deaths 190 -> 359 vs v18 (wins 24 vs 25 of 42)
inline constexpr bool CAPTURE_NEEDS_HOLD = false; // measured: 27 -> 25 of 42 vs v18
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
// Help requests: a champion in a contested skirmish asks for backup through
// shared memory; idle allies within reach walk over.
// Off: measured 2026-10-20 it pulled farmers into late, piecemeal fights - mirror
// 6/18, ~16-20 rounds slower vs the starters, 33 -> 40 deaths vs the old bot.
// Byte 7 stays free; the repacked capture byte alone matches the old layout.
inline constexpr bool HELP_CALLS = false;
inline constexpr float HELP_MIN_RATIO = 0.6f;   // enemy power / ours that is worth calling for
inline constexpr float HELP_MAX_RATIO = 2.5f;   // beyond this, backup arrives too late
inline constexpr int HELP_RANGE = 22;           // answer calls this close (Chebyshev)
inline constexpr float HELP_MIN_HP = 0.6f;      // only healthy allies answer
// Draft synergy: Tavi buys shards anywhere and stuns to peel, so he pairs with a
// front-liner (Marcella, Varg, Ryth) who screens him.
// Measured 2026-10-20: mirror 11/18 (parity 9/18), old Python bot 453 -> 442
// rounds, starters unchanged (deaths 10 -> 18 across both).
inline constexpr bool DRAFT_SYNERGY = true;
inline constexpr float SYNERGY_BONUS = 1.2f;
// Score-aware play: far ahead, bank small bags to protect the lead; far behind,
// bank bigger bags and stand and fight a loaded enemy instead of disengaging.
// Measured 2026-10-20: the behind half changed nothing measurable (rarely 150
// behind) -> off. Ahead half ungated: mirror 8/18, starter-python 15 rounds slower,
// old bot 18 rounds faster. Gated on a recent enemy sighting: mirror 10/18,
// starter-python 424 -> 419, starter-cpp and old bot level -> shipped.
inline constexpr bool SCORE_POLICY = true;
inline constexpr bool SCORE_AHEAD = true;    // ahead half: small banks
inline constexpr bool SCORE_BEHIND = false;  // behind half: big banks, bounty fights
inline constexpr int LEAD_MARGIN = 150;      // tributed-gem gap that counts as "far"
inline constexpr int AHEAD_BANK_BAG = 20;
inline constexpr int BEHIND_BANK_BAG = 60;
inline constexpr int BEHIND_BOUNTY = 40;     // behind: fight an enemy carrying this many
inline constexpr int AHEAD_THREAT_ROUNDS = 20;  // ahead: bank small only if an enemy was seen this recently
// Endgame denial: once the enemy nears the 1,000-gem finish while ahead of us,
// lock altars we pass and hunt loaded enemies instead of farming.
inline constexpr bool ENDGAME_DENIAL = true;
// Measured 2026-10-20, mirror vs the build without denial (parity 9/18):
// 850 -> 12/18, 700 -> 14/18, 650 -> 13/18, 600 -> 14/18, 500 -> 13/18.
// Starters and the old bot never trigger it (we are never behind a 700+ enemy).
inline constexpr int DENY_ENEMY_GEMS = 700;  // enemy tributed gems that start denial
inline constexpr int DENY_HUNT_BAG = 20;     // chase visible enemies carrying this many
inline constexpr int DENY_CHASE_RANGE = 8;
inline constexpr int DENY_LOCK_BAG = 0;    // denial locks only with an enemy carrying this many near the altar, 0 = always (10: 12/28 vs v15)
inline constexpr int DENY_LOCK_RANGE = 6;
inline constexpr bool SAFE_FALLBACK = false;  // no safe route: step to the least-exposed progressing tile (13/28 vs v15)
// Detour banking: tribute when an altar is nearly on the way to the next target,
// measured as dist(me, altar) + dist(altar, target) - dist(me, target).
// Measured 2026-10-20 (mirror parity 9/18): detour on top of the near-altar rule
// 6/18 (too many trips); replacing it: detour<=2 8/18, <=4 13/18 (43 deaths vs ~56),
// <=6 13/18, near rule simply removed 12/18. Cost: starter-python 419 -> 442
// rounds; starter-cpp 427 -> 422, old bot 440 -> 437. Most of the gain is no
// longer tributing tiny bags whenever an altar is within 4 tiles.
inline constexpr bool DETOUR_BANKING = true;
inline constexpr int DETOUR_MAX = 4;             // extra tiles worth walking to bank
inline constexpr int DETOUR_MIN_BAG = 10;
inline constexpr bool DETOUR_REPLACES_NEAR = true;  // drop the "altar within 4 tiles" rule
// Counter-draft from the enemy's revealed picks: area damage punishes Cassi &
// Issac (one kill takes both), divers punish two or more fragile ranged picks.
// Off: measured 2026-10-20 it changed no picks in practice - our draft already
// opens Varg / Cassi & Issac / Stellar (the AoE and dive answers), and early
// picks are made before the enemy's are revealed. Mirror 8/18, others level.
inline constexpr bool COUNTER_DRAFT = false;
inline constexpr float COUNTER_BONUS = 1.0f;
// Aggro handoff: awake camps hit the nearest champion within 3 tiles. When an
// enemy closes in on a camp we are fighting, step so the enemy is nearer.
// Off: measured 2026-10-20 mirror 9/18 (parity), starter-cpp 422 -> 443 and old
// bot 437 -> 448 rounds - stepping back stalls our own clear more than the camp
// hurts the enemy.
inline constexpr bool AGGRO_HANDOFF = false;
// Ghost tracking: an enemy that leaves vision is remembered for a few rounds as a
// fading threat whose reach grows a tile per round. Only bag carriers use it.
// Measured 2026-10-20: mirror 9/18 (parity), starter-cpp 422 -> 419,
// starter-python 442 -> 430, old bot level (437/438, deaths 33 -> 31).
inline constexpr bool GHOSTS = true;
inline constexpr int GHOST_ROUNDS = 8;
inline constexpr int GHOST_MAX_SLACK = 3;
inline constexpr int GHOST_MIN_BAG = 10;
inline constexpr int GHOST_POWER = 1;  // ghosts in side_power: 0 off, 1 while carrying a bag (17/28 vs v14), 2 always (14/28)
inline constexpr bool GHOST_BANKING = true;  // a ghost near a 20+ bag also triggers threat banking
// Pooled squads: for big hostile groups (elk herds) the squad rotates the tank, so
// also try the pooled-health solve and take whichever needs fewer helpers.
// The three switches below are OFF - measured 2026-10-20 against v13 on the
// ladder maps they target: they beat the passive starters (stampede 360 -> 1080
// gems) but lose to an opponent that fights back - our squad softens the elk
// herd / monolith, takes deaths, and the opponent finishes it (stampede 0/2,
// contest 0/2 vs v13). Dash-to-islands alone 1/2 on ambush (48-gem islands
// pull champions away); pooled + dash together 2/2 on ambush only.
// Pooled squads back ON 2026-10-20 (v16) for the 21-map ladder pool (stampede is
// gone): capped at 3 helpers, 30/42 vs v15 and 40/42 vs the old bot. It unlocks the
// 168-gem groups on islands (v15 got 0 gems there) and elk_arena/corridors herds;
// uncapped, eight's herds asked for 5 of 6 bodies and the squads deadlocked.
inline constexpr bool POOLED_SQUADS = true;
inline constexpr float SQUAD_POOL_SHARE = 0.60f;
inline constexpr int SQUAD_POOL_MAX_HELPERS = 3;  // pooled solve asks for at most this many helpers (cap 1/2/3/4/none vs v15: 24/27/30/25/26 of 42)
// Monoliths are fought anyway when they hold this share of the map's gems.
inline constexpr bool MONOLITH_WHEN_DOMINANT = false;
inline constexpr float MONOLITH_DOMINANT_SHARE = 0.5f;
// Champions with a dash path over holes (dashes cross them) to reach walled-off
// "island" camps; each hole crossing waits for the dash cooldown.
inline constexpr bool DASH_ISLANDS = false;
inline constexpr int DASH_TRIP_PENALTY = 8;
// Vulture: when visible enemies are fighting a big hostile group (elk herd or
// monolith) and it is nearly dead, go finish it and take the capture.
// Off: measured 2026-10-20 mirror vs v13 16/34 (parity 17) - the opening (a big
// group nearly dead with enemies on it, in our vision) almost never arises.
inline constexpr bool VULTURE = false;
inline constexpr float VULTURE_MIN_HP = 4000.f;    // "big": monolith or this much total health
inline constexpr float VULTURE_HP_FRAC = 0.35f;    // swoop once it is below this share of health
inline constexpr int VULTURE_RANGE = 12;           // how far we will travel for it
inline constexpr int VULTURE_MAX_TURNS = 15;       // we must be able to finish it this fast
// Carrier safety (v13 ladder: 47 deaths with 40+ gems handed 3,828 gems away).
// Measured 2026-10-20 on the 14-map pool: all three together 15/28 vs v13 (alone:
// split 11, safe altars 13, pvp banking 14); vs the old ganker bot 27/28 like
// v13 but deaths 93 -> 80; elk_arena won both sides. Shipped together as v14.
inline constexpr bool PVP_BANKING = true;       // bank smaller bags while enemies are active
inline constexpr int PVP_BANK_BAG = 30;
inline constexpr int PVP_RECENT_ROUNDS = 40;    // "active": an enemy seen this recently
inline constexpr bool SAFE_ALTARS = true;       // skip altars with enemies (seen or remembered) near
inline constexpr int ALTAR_THREAT_RANGE = 6;
inline constexpr bool SPLIT_CAPTURES = true;    // allies share big rewards: smaller bags, shorter tributes
inline constexpr int SPLIT_MIN_GEMS = 60;
// Empty-group skip: a target next to us with no visible live camps and no reward
// is skipped for a while. Fixes a full-game deadlock on boss_battle (a capturer on
// the spawn tile boxed in by allies waiting for camps that cannot respawn under him).
inline constexpr bool EMPTY_GROUP_SKIP = true;
inline constexpr int EMPTY_GROUP_TURNS = 4;
inline constexpr int EMPTY_GROUP_SKIP_ROUNDS = 20;
// Blocked altars: when no tribute tile can be walked to (all walled off or occupied),
// stop trying to bank for a while and keep farming gold - the tiebreak.
// Measured v17: boss_battle gold 1-4K -> 60-70K, 8/8 vs v16/starters/old bot; 24/42 vs v16 overall.
inline constexpr bool BLOCKED_ALTAR_FARM = true;
inline constexpr int BLOCKED_ALTAR_ROUNDS = 25;
// Shopping.
// Tuned 2026-10-20 one at a time (mirror vs current, old bot rounds, baseline 438):
// SHOP_TRIP_GOLD 100: 10/18, 434; 220: 7/18, 439. RECALL_SHOP_GOLD 180: 8/18, 455;
// 400: 10/18, 477. BANK_BAG 36: 9/18, 436; 64: 9/18, 442 (48 kept: flat).
inline constexpr int SHOP_TRIP_GOLD = 100;
inline constexpr int RECALL_SHOP_GOLD = 270;
inline constexpr int LOCK_MIN_GOLD = 40;
}  // namespace Cfg

// 8-byte shared memory layout.
namespace Mem {
inline constexpr int CLAIMS = 0;        // bytes 0..5: claimed group id + 1 per body
inline constexpr int MAX_BODIES = 6;
inline constexpr int CAPTURE = 6;       // low 7 bits: captured group id + 1; top bit flips per capture
inline constexpr int HELP = 7;          // low 7 bits: map sector + 1 of a fight asking for backup;
                                        // top bit = round parity, rewritten every round while live
}  // namespace Mem
