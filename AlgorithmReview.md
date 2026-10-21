# Algorithm review of `bots/kessoku` (internal v24), 2026-10-21

Scope: `bot.cpp`, `common.h`, `draft.cpp`, `GameRules.md`, `BotAPICpp.md` (distance_field, bitboard), plus ladder summaries (254 games of the previous build) and local sweeps (35 maps both sides, parity 35/70).

## Constraints that decide what is worth doing

- Fuel: 100k per champion per turn, metered per champion; every champion is its own wasm instance (no shared memory except 8 bytes; vision is not shared). Draft turn 1 gets 1M fuel and sees the whole map; the 1,024-byte draft memory is readable by every champion during the match (the current `draft.cpp` writes a plan nobody reads).
- Fuel pressure is local: 19 of 254 ladder games had >= 50 fuel-exhausted events (lanes 113/game, big_world 90, yellow_brick_road 52); average 13.6. Win rate in those games was 63% vs 52% elsewhere, so **execution speed is not what loses games**. Any case for an algorithm must be strategic.
- Terrain is static; all moves cost 1 (8-neighbour); the SDK's `distance_field::compute/compute_to` is a bitboard flood fill with `max_distance` and early stop, plus `import_linear_buffer`. A hand-written A*/Dijkstra in wasm will be slower than it.
- What loses games (ladder, 254 games): deaths (wipes 2.96/game in losses vs 0.83), and gem-poor targeting (in the dip, opponents got +19% gems per camp damage, +37% early gems per round; collected-gem lead at round 300 decides 75-80% vs 33% of games).

## Candidates, in the order asked

### 1. BFS / Dijkstra / A* / multi-source

- Decision: where to walk (`move_to`), which group is nearest (`choose_target`).
- Current: goal-rooted BFS with early stop, run per move; a second BFS when a danger mask exists; a full-map BFS from the champion every 4 rounds (`here`, about 32K fuel on 100x100) plus a detour field (about 27K).
- Verdict: **keep BFS**. A* gives nothing on unit-cost grids with a bitboard flood fill. Dijkstra only makes sense for soft danger costs near the champion (radius 4, <= 81 tiles, cheap), but the closest tested variant (`SAFE_FALLBACK`, least-exposed progressing step) was negative (13/28 earlier), so the benefit is unproven. Skip.
- Cost: BFS O(W x H) = 10k tiles on 100 x 100; memory a bitboard + 20 KB field.

### 2. Reverse search from valuable targets (cached static fields)

- Decision improved: scoring every group needs dist(me, group). Today that is one BFS from me per re-score. Terrain is static, so a BFS **rooted at each group** (and each altar) can be cached once and reused forever: dist(me, g) = field_g.get(me) in O(1), group-to-group and group-to-altar distances come free, and the detour test becomes `min_a A_a(me) + G_g(a) - G_g(me)` with no new BFS.
- Complexity: build G fields (G <= 58 groups, <= 18 altars): G x O(W x H); memory G x 2 bytes x W x H = 0.6 MB at 30 groups on 100 x 100, 0.4 MB at 58 on 60 x 60. Build lazily, one field per turn when `fuel_remaining()` is above a margin, so the first re-scores use the old path.
- Fit: yes, amortized. A re-score drops from about 45K to about 6K fuel (G lookups), removing most `fuelExhausted` events on lanes and big_world.
- Strategic benefit: **none by itself.** Measured: re-scoring every round instead of every 4 is much worse (20/70 vs live, 46/70 vs the field-comp proxy bot), re-scoring every 12 is neutral/better (37/70, 61/70 vs 53). Commitment beats reactivity, so cached fields are an enabler for items 3 and 4, not a win on their own.
- Plan: new `field_for(group)` accessor in `Bot`, falling back to the current `here` path while a field is missing. No change to scoring semantics, so it can be verified by identical decisions (same method used for v20's DETOUR_CACHE).

### 3. Dynamic programming, beam search and bounded lookahead (target tours)

- Decision improved: `group_score` picks one next group by `value / (travel + kill + capture + 4)`. The group set is small (<= 58), distances are exact (item 2), and groups have known respawn windows, so the problem is an orienteering/time-window routing problem that a one-step greedy cannot see: ping-pong between distant groups (seen on islands earlier), arriving as a group is still respawning, and not chaining the bank trip.
- Algorithm: beam search of depth 3 over candidate groups (top 8 by score), beam width 4, state = (current group, time, bag), objective = gems+gold value over elapsed time including the cheapest altar visit when the bag crosses the bank rule; commit to the first leg and **replan only on events** (target dead, reward taken by someone else, outmatched, bank, death), given the commitment result above.
- Complexity: 8 x 4 x 3 = ~100 node evaluations x O(1) distance lookups, a few thousand fuel; memory negligible. Exact DP over bitmask subsets is not needed at depth 3.
- Exchange-argument note: for repeated stationary farming the ratio-greedy is already optimal; the gain exists only through respawn windows and travel chaining, so the beam must be given those.
- Strategic benefit (HYPOTHESIS, unmeasured): higher gems per clear. In the dip, opponents averaged 16.7 gems per clear vs our 14.0, and 7.3 -> 8.3 gems per 1k camp damage vs our 6.9. It would not by itself fix fights.
- Plan: add `plan_tour()` returning a first-leg group id behind a `Cfg::TOUR_PLAN` flag; `choose_target()` calls it when the flag is on and falls back otherwise.

### 4. Opening plan from the draft (assignment problem, exact, precomputed)

- Decision improved: the first 300 rounds, where the result is mostly decided (mean collected lead at r300: +65 in wins, -20 in losses).
- Current: each body picks greedily from the same spawn, coordinated through the claim bytes as they are written in turn order.
- Algorithm: in draft turn 1 (1M fuel, whole map visible) build the group fields from item 2 and solve a small assignment of the 6 bodies to ordered groups (3-4 each) that maximizes gems+gold by round ~300, using a Hungarian algorithm (6 x G) or greedy-plus-2-opt over per-body tours; write the plan (6 bodies x 4 group ids = 24 bytes) into draft memory. Champion roles are known to be Vesper/Tavi/Willow/etc. (draft is fixed), so slot-based assignment works with approximate dps.
- Complexity: G fields (<= ~900K fuel on a 100 x 100 map with 30 groups: borderline, so cap at the 12 groups nearest the spawn) + Hungarian O(6^2 x G). Memory: tiny.
- Fit: only in the 1M-fuel draft turn; the 2x first play turn (200k) is not enough. Fails safe: if the plan is absent or stale, use the greedy path.
- Strategic benefit (HYPOTHESIS): better opening coverage and fewer duplicate early targets. Unmeasured.
- Plan: replace the dead `plan[]` bytes in `draft.cpp`; in `choose_target()` read the plan for the first N rounds.

### 5. Minimax, expectimax, MCTS

- Decisions: fight vs retreat, tribute vs flee. Verdict: **reject full-game search.** Fog (vision 8, not shared), 8 bytes of team memory, and unknown opponent code mean the state is not observable, and the evaluation function, not the search, is the bottleneck. A bounded **deterministic focus-fire simulation** is justified instead (item 6).

### 6. Bounded fight simulation instead of the Lanchester product

- Decision improved: `side_power` = total HP x total damage per round, used by `outmatched`, `losing`, `OUTMATCHED = 1.25`, target gating and deny. It ignores burst timing (a 1,100-damage cast once per 8 turns), stuns, range, and that a **tribute channel makes the carrier a punching bag for `ceil(bag/10)` turns** (the `bank()` call at an altar with enemies in 6 tiles has no such check).
- Algorithm: for the visible group (<= 6 vs <= 6), simulate 8 rounds of greedy focus-fire (each side kills the lowest-HP killable target, spells fire once at round 0 and again at round 8, stuns skip a round, ranged/melee reach by distance); the result is survivors' HP for both sides. O(N^2 x T) = about 300 operations, a few thousand fuel; memory negligible.
- Fit: yes, once per turn when foes are visible.
- Strategic benefit: addresses the dominant loss driver (deaths; wipes). Evidence that the current evaluator is the limit: threshold tuning is flat or negative (RETREAT 0.40, FIGHT margin 0.35, LOSING_RANGE, BURST_RETREAT all tested); what moved results was stats (health shards, -40% deaths), not thresholds. Limit: it only sees what is in vision, so it cannot fix fog.
- Plan: new `float fight_value(vec2 at)` used where `side_power` is compared today, behind `Cfg::FIGHT_SIM`; start by replacing only the tribute-start check in `bank()`, then `outmatched`.

### 7. Banking policy (optimal stopping / square-root law)

- Decision: when to leave a fight or a farm for an altar. Model: renewal-reward with income lambda = 0.120 gems per body-round (ladder), death hazard h = 0.00203 per carrying-round (ladder, bag-independent), round-trip overhead T. The model's best bag is 11-29 for T = 10-120 vs the live 48, and it predicts a 10-30% throughput gain.
- **Tested and refuted in practice:** BANK_BAG 30 / 70 and PVP_BANK_BAG 20 / 45 on the current build move results by +/-3-5 wins (30: 58/70 and 40/70 vs the proxy and the live build; 70: 58 and 38; PVP 20: 56 and 40; PVP 45: 54 and 31) against 53/70 for the live build. Flat within noise, as in the earlier 36/48/64 tests, so the model overstates the gain (trip overhead is already low because of detour banking). Not recommended.

### 8. Other candidates, rejected

- **Global assignment (Hungarian/auction) during play:** bodies do not see each other beyond 8 tiles; the 8-byte memory cannot carry positions. The opening plan (item 4) is the one case where all information is known to all bodies.
- **Sharing intel through the free memory byte** (death location, calls for help): both variants measured worse (39/70 vs 43/70, 5/10).
- **Articulation points / connectivity:** reachability is already implicit in the cached fields (distance = unreachable). Chokepoint-aware squad movement would help only a few maps; skip.
- **Hashing / lookup tables / more bitboards:** the engine's bitboards are already used for danger, goals and terrain; spell and stat lookups are not hot. Skip.
- **Memoizing `burst_at`:** 81 tiles x foes per turn; not a bottleneck.

## Top three, by expected competitive payoff

1. **Bounded fight simulation (item 6), starting with the tribute-channel check.** Targets deaths, the largest loss driver, and it is the only change that breaks the plateau where threshold tuning is flat. About 150 lines, behind a flag, A/B-able on the existing sweep.
2. **Cached reverse fields + committed beam tour planner (items 2 and 3).** The fields are an enabler (execution only); the tour is the strategic part and addresses gems per clear. Replanning must stay event-driven; per-round re-scoring is measured to be worse.
3. **Opening plan from the draft's 1M-fuel turn (item 4).** The opening decides most games, the information is exact and shared, the draft memory channel already exists but is unused, and it falls back to the current behaviour. Needs item 2's fields, so build it second.

Order: 2 (fields only, identical decisions) -> 1 -> 3 (tour planner and opening) with each step A/B-tested against the frozen live bot and the field-comp proxy bot on all 35 maps, both sides.
