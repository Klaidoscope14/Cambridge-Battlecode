# Performance audit of `bots/kessoku` (internal v25), 2026-10-21

Three things are kept apart throughout: **execution speed** (fuel), **legal-action reliability** (does the bot always act legally and on time), and **match strength** (does it win). Measured numbers come from an instrumented copy of the bot (harness saved in `Submission/tools/fuel_profile/`), run against the field-comp proxy bot `zmeta` on six maps, plus the 360 ladder summaries I already had.

## 1. Runtime constraints (from `GameRules.md` and `BotAPICpp.md`, nothing invented)

- C++ bots get **100k fuel per turn** (Wasmtime fuel, roughly instructions, deterministic). Draft turn 1 gets 10x, each champion's first play turn 2x. Unused fuel is **not** carried over.
- Fuel is **per champion**: each champion is its own wasm instance with its own budget, so 6 bodies do not share one pool.
- Running out is **not a crash or forfeit**: the bot is suspended, the next bot goes, and the turn **resumes at the same instruction the next round**. `bc::fuel_remaining()` exposes the budget.
- `--release` (and the platform) skips `debug_block`. The docs I read give no wasm memory cap; I did not measure memory use and make no claim about it.
- Wall-clock is not limited by the rules text; only fuel.

## 2. Measured profile (kessoku v25, 5 bodies, 500-1500 rounds per map)

| Map (tiles) | avg fuel/turn | turns > 80k | turns > 95k | note |
|---|---|---|---|---|
| 01big_world (10,000) | 43,127 | 5.0% | 0.6% | v24 behaviour (fields off): 16.9% / 3.7% |
| 00lanes (2,700, 18 altars, 47 groups) | 47,107 | 9.0% | 2.1% | fields off: 10.8% / 2.5% |
| 00corners (5,041) | 38,743 | 1.9% | 0.2% | fields off: 5.3% / 0.2% |
| 00expanse (6,400) | 39,002 | 1.3% | 0.3% | fields off: 2.8% / 0.1% |
| 00split (1,575) | 42,336 | 2.9% | 0.5% | fields off: 4.5% / 1.0% |
| 01hooks (961) | 27,789 | 0.1% | 0.1% | |

Average use is 28-47k of 100k, so there is **over 50% headroom on average**, but 1-9% of turns exceed 80k and about 0.1-2% exceed the budget and get suspended (ladder: 13.6 suspended turns per game on average, 100-145 on `00lanes`, 62-90 on `01big_world`). Turns above 100k in the table include each body's 2x first turn and turns that span a suspension.

Inclusive fuel per call (lanes / big_world / corners), `kprof`:

| Function | lanes | big_world | corners |
|---|---|---|---|
| `observe` (every turn) | 17.0k | 14.3k | 13.1k |
| &nbsp;&nbsp;`obs.champion_lists` | 4.5k | 5.3k | 4.2k |
| &nbsp;&nbsp;`obs.group_state` | 5.2k | 4.3k | 4.1k |
| &nbsp;&nbsp;`obs.safe_camps` | 3.2k | 2.0k | 2.0k |
| &nbsp;&nbsp;`obs.live_hp` | 2.1k | 0.8k | 1.0k |
| `choose_target` per re-score | 11.5k (max 60k) | 7.8k (max 82k) | 9.7k (max 46k) |
| `group_score` per group | 427 (47 per re-score = ~20k) | 367 | 424 |
| `move_to` | 9.9k (max 59k) | 16.9k (max 28k) | 10.9k (max 18k) |
| `bank` | 34.3k (max 53k) | 23.1k | 18.3k |
| &nbsp;&nbsp;`bank.altar_loop` | 22.6k | 6.1k | 4.8k |
| `ensure_here` BFS (big map) | - | 15.1k avg (max 33k) | 4.2k |
| `build_group_fields` | - | max 70.7k in one call | - |

Shares of all fuel: `observe` 16-28% (18.6% on big_world, 20.2% on lanes, 15.7% on corners in the finer profile; 28% in an earlier run of the same map), `farm` 31-41% inclusive (contains `choose_target` and `move_to`), `choose_target` 13-16%, `move_to` 7-18%, `assess_threat` 3-5%, `bank` 3-4%.

Caught exceptions: 0 in all 12 profiling games; `botFaults` 0 in 360 ladder games.

## 3. Findings, with code locations

### 3.1 Repeated calculations and redundant reconstruction

1. **`Bot::bank()` (bot.cpp:1720) is O(A^2) per call**, A = altars. `threatened(a)` scans `altar_tiles` to find a's index every time it is called (twice per altar), `reachable(a)` rebuilds a bitboard and walks its tiles per altar every call although it is static, and `goals |= square(a, 1)` builds a fresh bitboard per altar. On `00lanes` (A = 18) the altar loop alone is 22.6k fuel. **Fixed in a test copy** (`kessoku_perf_bank.diff`): index loop, `altar_sq[]` and `altar_reach[]` cached lazily. Measured after: `bank` 34.3k -> 13.9k per call on lanes, 18.3k -> 12.2k on corners. Complexity O(A^2 x bitboard) -> O(A x bitboard-OR), the remaining cost is the BFS inside `move_to`.
2. **`Bot::observe()` (bot.cpp:230) rebuilds state every turn.** Largest steady cost. Candidate savings (not implemented, so the estimates are mine):
   - `obs.group_state` loops over all groups and all their tiles, then calls `g.handle.state()` for every visible empty group. A static per-group centre/radius plus `cheb(pos, centre) > 8 + radius` skips groups that cannot be visible: O(G x T) -> O(G) cheap tests + O(visible). Ward vision is never used by this bot, so vision radius is exactly the champion's 8 and the skip is exact.
   - `obs.live_hp` and `obs.mates` are only needed when a fight, a squad or a re-score happens; compute lazily on first use per turn.
3. **`Bot::move_to()` (bot.cpp:347)** allocates a `bc::distance_field` (up to 20 KB at 100 x 100) and rebuilds `blocked_now()` (4 bitboard unions plus 3 vision API calls) on every call, and runs up to two BFS when a danger mask exists. A member scratch field and a per-turn cached `blocked` (invalidated after any kill or own move) removes the repeated reconstruction. Exact if invalidation is right.
4. **`build_group_fields()` (bot.cpp:620)** builds fields in id order, not by usefulness, one champion at a time, and all 6 champions build the same static fields (no sharing across instances; the 1,024-byte draft memory is too small to ship them). Until every field exists, `choose_target` falls back to the full-map BFS (`ensure_here`, 15k avg on big_world). Build nearest-first (by `spawn_field`) so the fields that matter exist first.
5. **`choose_target()` (bot.cpp:631)** re-scores all G groups every 4 rounds (47 x 427 = about 20k on lanes). Cheap early exits (respawn window, claimed-without-strength) before `required_helpers`, and a per-round cache of `required_helpers` and `side_power`, cut that without changing the answer.

### 3.2 Graph searches

- BFS is the right algorithm here: unit costs, bitboards, engine-implemented flood fill with early stop (`compute_to`). Do not replace it with A* or Dijkstra; they would be slower in wasm and add no accuracy.
- Redundant searches are the issue, not the algorithm: full-map `here` BFS on re-score (largely removed by the v25 group fields), `detour_field` per target (cached already), two BFS in `move_to` when danger exists.

### 3.3 Allocations and dynamic structures (hypothesis, not isolated by the profile)

Per turn the bot builds fresh `std::vector`s: `enemies`, `allies`, `mates`, `foes`, `camps`, `live_hp`, a local `living`, `cands`, and in `assess_threat` a `dead` vector plus `bc::champions(team::enemy)` whenever a ghost exists. I did not measure allocation cost separately; plausible savings are a few thousand fuel per turn. Make them members with `clear()` + `reserve()` (capacity persists across turns). This is also the safest optimization to test for exact equivalence.

### 3.4 Memory layout (estimate, not measured)

Each `Group` carries a `bitboard` (about W x H / 8 bytes: 1.25 KB at 100 x 100) and each cached field is 2 bytes per tile (20 KB at 100 x 100): about 0.6 MB for 30 groups, 0.4 MB for 58 groups at 60 x 60, per champion. I found no stated memory cap; if one exists this is the first place to check.

### 3.5 Expensive branches with little benefit (measured, strength not helped)

- `TOUR_PLAN` (beam over tours): 11/70 vs v24 and 39/70 vs the proxy: costs little fuel, lowers strength. Stay off.
- `FIGHT_SIM_OUTMATCHED`: 35/70, deaths down 359 -> 306 vs the proxy but not a win-rate gain; `FIGHT_SIM_TRIBUTE` never fires locally. Both off.
- Re-scoring every round: 20/70 mirror (worse). Every 8 or 12 rounds: mixed (v25 comment).
- `FUEL_GUARD`: 20/42 vs the older build (worse, it changes decisions).

### 3.6 Worst-case spikes

Spikes are stacked jobs in one turn: a re-score (20-82k) + `bank` (to 53k) + `move_to` (to 59k) + a field build. `build_group_fields` itself can spend up to 70.7k in one call (loop builds while `fuel_remaining() >= 45,000`; each BFS up to 33k at 100 x 100, so it leaves 12-45k, safe by design but a spike by size). There is no preemption inside the engine's `compute`, so the only safeguard is deciding before the call.

## 4. Separating the three goals

| | Evidence | Verdict |
|---|---|---|
| Execution speed | average 28-47k of 100k; 1-9% of turns above 80k; v25 fields cut heavy turns on big maps (big_world 16.9% -> 5.0%) | Real but local to big or many-altar maps |
| Legal-action reliability | 0 bot faults in 360 ladder games, 0 caught exceptions in 12 profiling games; suspensions are legal by the rules and resume | Not at risk; the risk of a suspension is a stale snapshot (an action one round late), which the `try/catch` blocks absorb |
| Match strength | ladder: games with >= 50 suspended turns won 63% vs 52% otherwise; local: GROUP_FIELDS 37/70 vs v24, bank optimization 58/70 vs 59/70 baseline (same), DETOUR_CACHE 21/42 earlier | **Faster code has not shown any strength gain.** Do not expect rating from the optimizations in section 3 |

## 5. Computation-allocation policy

Principle: never spend fuel to save fuel; spend it where a wrong decision costs games. Measured losses come from fights and early target choice, not from latency.

| Tier | Jobs | Rule |
|---|---|---|
| 0, always (target <= 15k) | legality, own state, `assess_threat`, retreat/escape, attack and ability use | never gated, runs first so a suspension cannot delay it |
| 1, routine, skippable | `choose_target` re-score, `build_group_fields`, shop, ghost refresh, support abilities | run only when `fuel_remaining() >= estimate + 20k reserve`; re-score is event-driven (target dead, respawn, claim change) plus a timer; estimate = rolling max of the last 8 observed costs of that job |
| 2, consequential, spend more | tribute start with enemies within 6, fights with lethal or outmatched margin, retreat decisions with a bag >= 20, the first 300 rounds, final 100 rounds, denial | allowed to use the reserve; candidates: the bounded fight simulation (exists, off) and a wider target look-ahead |

Honest limit: the Tier-2 candidates tested so far (tour planner, fight sim) did not raise win rate locally, so the policy mainly protects against spikes and frees fuel; it does not by itself make decisions better. New uses of spare fuel have to be proven by A/B first.

## 6. Profiling and benchmarking plan

1. Copy `Submission/tools/fuel_profile/` into a scratch bot: `prof.h` (RAII `PROF("name")` scopes, `MARK` blocks, per-turn histogram), `main_profile.cpp` (prints cumulative stats every 500 rounds), `parse_prof.py`.
2. Run `cambc run <profbot> zmeta --map maps/<map>.map26a --release --log-limit 30000000 -o <dir>`; read `team-a.stdout` from the bundle (strip NUL bytes).
3. Maps: 01big_world, 00lanes, 00corners, 00expanse, 00split, 01hooks (extremes in size, altars and groups); both sides.
4. Metrics: average, p99 and max fuel per turn; share of turns above 80k and 95k; per-function inclusive fuel; suspended turns per game from the summary `fuelExhausted` events; caught exceptions (`bot error` lines); `botFaults`.
5. Acceptance: no function's p99 rises; turns above 95k do not increase; zero new caught exceptions.
6. Per change, also run the 35-map A/B (`tools/ab.py`) against the frozen live bot for strength (parity 35/70).

## 7. Safe C++ implementation suggestions

- Cache only static data (terrain, altar and group geometry); cache per-turn data only with an explicit invalidation point after any kill, own move or ability that changes vision.
- Reuse scratch objects as members (`std::vector::clear` keeps capacity; reuse `bc::distance_field` and `bc::bitboard` buffers).
- Fill lazily on first use, not in `init()`: the first-turn branch `if (bc::fuel_remaining() < 60000) return;` (bot.cpp:1924) turns any extra init cost into a different game. This was observed: moving the cache from `init()` to first use turned one divergent game (`01the_farm_A`) back into an identical one.
- Keep the existing `try/catch` around vision-dependent calls; entities leave vision mid-turn.
- Prefer lookups by index over searching by value (`threatened(i)` instead of `threatened(vec2)`).

## 8. Worst-case runtime safeguards

1. **Budget gate** for Tier-1 and Tier-2 jobs: `if (bc::fuel_remaining() < cost_est[job] + RESERVE) skip`. `cost_est` comes from the measured rolling max, not constants (BFS cost scales with tiles: about 1.5 fuel per tile measured on big_world, 0.8 on corners).
2. **Never stack** two optional jobs above a combined estimate in the same turn: if a re-score ran, defer field building and any optional `bank` lookahead to the next turn.
3. **Field building cap**: at most one BFS per call unless `fuel_remaining() > 70k`; build nearest-first.
4. **Order of work**: Tier-0 decisions before any optional job so a suspension cannot delay them.
5. **Measure the suspended-turn rate** in every release (ladder `fuelExhausted` per game) and treat a doubling as a regression.

## 9. Test that an optimization preserves behavior

Matches are deterministic, so the strongest test is bit-for-bit equality of results. `Submission/tools/fuel_profile/equiv.py BASE_TAG OPT_TAG` compares two `tools/ab.py` runs (rounds, tributes, deaths, gold, winner per game) and reports fuel-exhausted counts.

Demonstration on the `bank()` change (`kessoku_perf_bank.diff`), 35 maps x 2 sides vs `zmeta`:

- First version (cache filled in `init()`): 39/70 identical; in the 19 games with no fuel pressure in either build, 18 identical, 1 different (`01the_farm_A`, caused by the init-time fuel crossing the 60k first-turn threshold).
- Final version (cache filled on first use): 55/70 identical; **19 of 19 games with no fuel pressure in either build are identical**. The other 15 games differ only where a suspension moved, which is expected when the code gets faster.
- Strength unchanged: 58/70 vs 59/70 for the baseline (same within noise); suspended turns 761 vs 763 in total (the change is too small to move them).

Pass criteria for any future optimization: identical signature in every game where neither build hit a suspension, no new caught exceptions, and 35-map A/B within noise of 35/70 against the frozen build.

## 10. What I would do, in order

1. Apply `kessoku_perf_bank.diff` (exact on unconstrained games, 2.5x cheaper `bank` on 18-altar maps, no strength effect). Optional.
2. Nearest-first field build and the `observe` group-state distance skip (together an estimated 4-6k fuel per turn on many-group maps; to be verified with the profile harness).
3. Add the Tier-1 budget gates only after (2), because `FUEL_GUARD` changed decisions in the past and lost.

Expect no rating change from 1-3; use any fuel they free only for ideas that first win an A/B.
