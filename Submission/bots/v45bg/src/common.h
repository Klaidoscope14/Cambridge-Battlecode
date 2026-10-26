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
inline constexpr float CLUSTER_VALUE = 1.0f;  // value multiplier for monster-free cluster groups (0.5: 36/70, off)
inline constexpr float ENEMY_NEAR_PENALTY = 0.40f;
inline constexpr float SWITCH_MARGIN = 1.30f;
inline constexpr int RETARGET_EVERY = 4;  // rounds between full target re-scores
// Algorithm review item 2: cached per-group distance fields replace the full-map BFS from
// us on each re-score (same distances; built one per turn from spare fuel).
// v25 (35 maps x 2): fields alone vs v24 37/70, field proxy zmeta 53 -> 59, zpoke 48 -> 52,
// zhor 61 -> 66, zrush 58 -> 57, zlock2 66 -> 65, camper/old bot/starters 70/69. Re-scoring every
// 8 or 12 rounds on top: totals over those five 267 / 256 vs 271 (better vs mirror/proxy, worse
// vs the ranged and Heart-of-Ruin bots) -> RETARGET_EVERY stays 4.
inline constexpr bool GROUP_FIELDS = true;
inline constexpr int FIELD_BUILD_MIN = 45000;  // spare fuel needed to build one more field
// Performance audit (PerformanceAudit.md, 2026-10-21): exact optimizations (identical decisions in
// every game without a fuel suspension), but faster code moves suspensions and re-rolls those games.
// Measured with bank + observe skip + move scratch vs v25 (35 maps x 2): mirror 38/70; zmeta 59 -> 56,
// zpoke 52 -> 49, zhor 66 -> 58, zrush 57 -> 59, zlock2 65 -> 66, camper/old bot 70, starters 69/68.
// Alone vs zmeta (v25 59): bank 55, observe skip 57, nearest-first fields 54 (fuel events 763 -> 925),
// one build per turn 56, move scratch 55 (events 731). No strength gain, so all OFF (= v25 behaviour).
// v26 = this source with all OFF: vs v25 on 9 opponents x 70 games, same winner in 629/630, the
// other a loss turned into a win; 624 games bit-identical (if constexpr keeps the code out).
inline constexpr bool BANK_CACHE = false;           // bank(): cached altar squares/reachability, index lookups
inline constexpr bool OBS_SKIP_FAR = false;         // observe: skip groups beyond vision radius
inline constexpr bool FIELDS_NEAREST_FIRST = false;  // build group fields nearest-to-spawn first
inline constexpr bool FIELD_BUILD_ONE = false;      // one field per turn unless fuel is plentiful
inline constexpr int FIELD_BUILD_MORE = 70000;
inline constexpr bool MOVE_SCRATCH = false;          // move_to reuses one distance-field buffer
// Algorithm review item 3: beam search over target tours (needs every group field built).
// Measured: 11/70 vs v24, 39/70 vs the proxy (look-ahead pulls bodies to far groups) -> off.
inline constexpr bool TOUR_PLAN = false;
inline constexpr int TOUR_CANDIDATES = 8;
inline constexpr int TOUR_BEAM = 4;
inline constexpr int TOUR_DEPTH = 3;
// Algorithm review item 6: bounded focus-fire simulation of the visible skirmish.
// Measured with re-score 12: tribute check gave identical games (never fires locally); with the
// outmatched sim too 35/70 (fewer deaths vs the proxy, 359 -> 306) -> both off.
inline constexpr bool FIGHT_SIM_TRIBUTE = false;    // refuse a tribute channel we would not survive
inline constexpr bool FIGHT_SIM_OUTMATCHED = false; // outmatched = we die, or they keep more health
inline constexpr int FIGHT_SIM_ROUNDS = 6;
inline constexpr float FIGHT_SIM_MARGIN = 0.15f;    // their remaining share minus ours that counts as losing
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
inline constexpr float PAIR_DRAFT_SCORE = 7.0f;      // draft value of the pick (9.6 -> 7.0: v23 review, 55/70 vs a Stellar/Ren/Varg/Ryth bot, was 43)
// Review 2026-10-21: after the Monster + Jungle emblem plan every shard went into Strength/Focus
// (172 Power Strength shards a game on the ladder): Vesper ended at ~690 Strength and 1385 HP. Buy
// Power Health shards at this percentage of the Power Strength/Focus shards bought (0 = old build).
// Measured vs the Stellar/Ren/Varg/Ryth bot on 35 maps both sides: 0 -> 43/70, 50 -> 54, 100 -> 54,
// 200 -> 51, 400 -> 50; vs the live v23 mirror 100 -> 45/70, deaths 903 -> 762.
// Re-measured v24 on the true 35-map pool (cambc 3.0.4; the 45 files incl. 10 duplicates): with the
// pair at 7.0, vs v23 45/70 (deaths 548 vs 895), field proxy zmeta 53/70 (= v23, deaths 595 -> 382),
// zpoke 33 -> 48, zhor 56 -> 61, zlock2 64 -> 66, zcamp/oldpy 70, starter-cpp 69.
inline constexpr int HEALTH_PCT = 100;
// Patch 3.0 (cambc 3.0.2, 2026-10-21), measured on the 35-map pool vs the v22 logic:
// - Heart of Ruin drafted at 10.0 / 9.0: 29/70 each (our bots retreat at 30% HP, so its
//   missing-health bonus never kicks in) -> not drafted. The old draft loop stopped at 11
//   choices and could not see it at all.
// - Ranged meta: Vesper, Tavi, Willow first + ranged move-reset/chase + dash strike 54/70
//   (deaths 687 vs 1352); Vesper first only 49/70; ranged draft alone 45/70; ranged
//   behaviour with the old draft 33/70. RANGED_META switches the draft (old scores if false).
// - Dash strike (aim dashes with landing damage/stun) 37/70; with Heart of Ruin 44/70 vs without.
inline constexpr bool RANGED_META = true;
// 3-champion maps: force only Vesper + Tavi, then score (picks Varg). Ladder v25 won 43% on 3-champion
// maps vs 55% on 5. Measured 2026-10-23 on the 6 local 3-champion maps: 125/132 vs 121/132, mirror 8/12.
inline constexpr int DRAFT3 = 2;  // 3 = always open Vesper, Tavi, Willow
inline constexpr float HOR_DRAFT_SCORE = 0.f;       // Heart of Ruin (added in cambc 3.0)
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
// Ladder 2026-10-25: in rounds 1-400 our bodies stand by unstarted camps 12.3% of the time (top 5: 6-7%).
// LESS_WAIT: shorter regroup/give-up clocks, and squad targets pay LW_TIME_PENALTY rounds per missing helper.
inline constexpr bool LESS_WAIT = true;
inline constexpr int LW_REGROUP_TURNS = 4;
inline constexpr int LW_GIVE_UP_TURNS = 12;
inline constexpr int LW_TIME_PENALTY = 10;
inline constexpr int regroup_turns() { return LESS_WAIT ? LW_REGROUP_TURNS : SQUAD_REGROUP_TURNS; }
inline constexpr int give_up_turns() { return LESS_WAIT ? LW_GIVE_UP_TURNS : SQUAD_GIVE_UP_TURNS; }
// Top-5 builds: Treasure first on every champion, then Jungle, then stacked Bruiser (5 + 1 + 1 shards of
// stats per 150 gold vs Power's 6).
inline constexpr bool TREASURE_FIRST = true;
inline constexpr bool BRUISER_ITEMS = true;
// Clear speed (top-5 builds, 2026-10-25): Vesper stacks Bruiser Strength (Fish 14 Str emblems, little Health);
// no top team buys Monster; every top team drafts melee bruisers (Vendetta, Marcella, Heart of Ruin).
inline constexpr bool VESPER_STR_STACK = true;
inline constexpr int VS_HEALTH_PCT = 0;         // Vesper's Health shards per 100 Strength shards when stacking
inline constexpr bool NO_MONSTER = false;       // skip the Monster emblem in every build
// Fights vs melee invaders (zmarc, 2026-10-25): 69% of our deaths in losses have no ally within 4, usually one melee
// enemy within 3; victims flee (59%), HP drains 82% -> 29% over 10 rounds, enemies near them rarely lose HP.
inline constexpr bool DUEL_STAND = true;     // one melee chaser that reaches us anyway: shoot back instead of fleeing
inline constexpr float DUEL_HP_RATIO = 2.0f;  // ... only if its HP is at most this times ours
inline constexpr bool FLEE_TO_ALLY = false;   // escape() prefers tiles nearer a healthy ally within 10 over home
inline constexpr bool RESCUE = false;         // converge() also joins a hurt ally being hit by 1-2 enemies
inline constexpr float RESCUE_RATIO = 0.8f;   // ... when our side power there is at least this share of theirs
// PAIRING: after any of us sees an enemy melee champion on our half (broadcast in byte 7, free while HELP_CALLS is off),
// ranged champions value groups with no ally within PAIR_RANGE (and no ally claim) at PAIR_ALONE_MULT for PAIR_WINDOW rounds.
inline constexpr bool PAIRING = true;
// BIG_GROUP_FULL_HP (01starfish side B: 13-24 deaths a game to the 14-camp centre elk group). live_hp sums only the
// camps we see, so a huge group seen at its edge looks soloable. For groups with >= BG_MIN_CAMPS fighting camps and
// strength >= BG_MIN_STR, count every unseen camp tile at full health. The gate is strict so ordinary maps are unchanged.
inline constexpr bool BIG_GROUP_FULL_HP = true;
inline constexpr int BG_MIN_CAMPS = 10;
inline constexpr float BG_MIN_STR = 300.f;
inline constexpr int BG_ALTAR_D = 0;
// BIG_GROUP_SQUAD: that group is worth taking as a team, not avoiding (118 gems on starfish): up to bodies-1 helpers,
// damage pooled at BG_POOL_SHARE of max health, and BG_WAIT_MULT x the regroup/give-up clocks while the squad gathers.
inline constexpr bool BIG_GROUP_SQUAD = false;
inline constexpr float BG_POOL_SHARE = 0.9f;
inline constexpr int BG_WAIT_MULT = 3;  // ... and an altar tribute tile this close (only starfish's centre group on the 70-map pool)
inline constexpr int PAIR_RANGE = 5;
inline constexpr int PAIR_WINDOW = 80;
inline constexpr float PAIR_ALONE_MULT = 0.25f;
inline constexpr bool PAIR_BRUISERS_ONLY = false;  // trigger only on Marcella, Heart of Ruin, Ryth, Vendetta
inline constexpr int MELEE_OPENER = 0;          // third forced opener: 0 Willow, 1 Vendetta, 2 Marcella
// Enemy threat.
inline constexpr float LETHAL_MARGIN = 1.15f;  // retreat when visible burst * this reaches our HP
inline constexpr float DANGER_TILE = 0.60f;    // avoid tiles whose burst exceeds this share of HP
inline constexpr float OUTMATCHED = 1.25f;     // enemy fight power over ours that counts as losing
// Ladder replays (2026-10-24): 97% of our deaths are untraded; victims flee and are run down
// (ranged champions cannot move and shoot in one turn), while allies within 8 tiles keep farming.
// STAND_SHOOT: when the chaser reaches us next turn whatever we do, fight back instead of fleeing.
// CONVERGE: join a skirmish a teammate is in when our side holds the fight power there.
inline constexpr bool STAND_SHOOT = false;  // v30: off. Ladder v29 (95 games) 45% vs ~52% expected, deaths/loss 18.5 vs 16.4
inline constexpr bool CONVERGE = true;
// Plan_v29 R2 FIT_FIGHT: "outmatched" = P(we die within 8 rounds) >= FIT_THRESHOLD, from a logistic model fitted
// to 223K skirmish rows of v30 vs zgank/zdive0/zpoke (40 maps x 2 sides). Test AUC 0.889 vs 0.705 for the
// OUTMATCHED power-ratio flag; at the flag's firing rate the death rate when it does not fire halves (1.7% -> 0.8%).
// Features (standardised): log hp ratio, log dps ratio, bodies diff, enemy stuns / dashes / resets ready, our
// hp share, burst/our hp (cap 3), enemy hp share, nearest/7, enemy ranged, bag/100.
inline constexpr bool FIT_FIGHT = true;
// CONVERGE_FIX (00reverse_spiral standoff, traced 2026-10-25): with the spawns adjacent, enemies standing on their
// own spawn (unreachable, healed to full every turn) kept converge() choosing a fight it could not act on, and it
// returned "done" anyway, so our champions stood on the spawn for 2000 rounds. Ignore enemies on their spawn, and
// only end the turn when converge() actually attacked or moved.
inline constexpr bool CONVERGE_FIX = true;      // converge() ignores enemies standing on their own spawn
inline constexpr bool CONVERGE_ACT_ONLY = false; // ...and ends the turn only if it attacked or moved (measured: worse alone, 113-122)
// SPAWN_TARGET_SKIP (same trace): ranged champions shot enemies standing on their own spawn (healed to full every
// turn) every turn; for ranged champions moving and attacking share one allowance, so they never walked off our
// spawn. In fights, ignore enemies on their spawn unless we can kill them this turn.
inline constexpr bool SPAWN_TARGET_SKIP = true;
// Measured 2026-10-25 (v35 = v31 + CONVERGE_FIX + SPAWN_TARGET_SKIP): reverse_spiral standoffs gone (real games in
// the mirror and vs v31/v30/zgank/zdive0); vs v31 on all 40 maps x zgank/zmeta/zpoke/zdive0: 243-243 (+5 -5);
// mirror 43/80. Each fix alone keeps the standoff; CONVERGE_ACT_ONLY was worse (113-122).
inline constexpr float FIT_THRESHOLD = 0.20f;
// Measured 2026-10-25 vs v30 (tools/sprt.py): threshold 0.043 24-32, 0.025 24-32 (both SPRT reject: fleeing more
// gets us run down), 0.09 46-47, 0.20 50-47 on 12 PvP maps vs zgank/zdive0/zpoke and 67-63 on 12 other maps vs
// zmeta/zhor/zrush, mirror 23/40 (deaths 553 vs 421); 0.35 37-44.
inline constexpr float FIT_MU[12] = {0.513183f, 0.517883f, 0.5948f, 0.154514f, 0.304904f, 0.703159f, 0.776666f, 0.0964759f, 0.711446f, 0.606188f, 0.305668f, 0.0604435f};
inline constexpr float FIT_SD[12] = {1.18152f, 0.883029f, 1.16514f, 0.370982f, 0.513387f, 0.660089f, 0.232796f, 0.28675f, 0.251096f, 0.258942f, 0.609684f, 0.147437f};
inline constexpr float FIT_W[12] = {-0.168161f, -0.743035f, 0.261229f, 0.0907772f, -0.0406176f, -0.168129f, -0.725709f, 0.0527242f, 0.401567f, -0.904956f, 0.11325f, -0.0560074f};
inline constexpr float FIT_B = -4.26618f;
// Measured 2026-10-24 (40 maps x 2 sides, vs v28): zgank 51/80 (44), field 338/400 (327), mirror 49/80;
// STAND_SHOOT alone 311 (mirror 40), CONVERGE alone 330 / zgank 52.
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
inline constexpr bool RANGED_MOVE_RESET = true;  // move, reset, attack in one turn
inline constexpr bool RANGED_CHASE = true;       // step toward a killable enemy, then fire
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
inline constexpr bool CAPTURE_ASSIGN = true;  // v25 re-test: off 29/70 (Vesper +33% gold on captures beats the idle bags)
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
