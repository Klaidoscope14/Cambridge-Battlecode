# Plan: changes on top of v29

Status: **plan only; nothing implemented.** Evidence: `LadderPatterns_v27.md` (all 1365 ladder-v27 =
internal v28 games). Base for every change: `Submission/bots/v29` (= current `kessoku.zip`: v28 +
STAND_SHOOT + CONVERGE). Sprint 3 locks on 31 Oct.

Ground rules (same as every earlier version):
- Each change is a `Cfg::` switch in `common.h`, OFF by default and gated with `if constexpr`. With every
  new switch OFF the build plays bit-identically to v29 (check with samewin/equiv before bundling).
- Build a variant per switch (`cp -r bots/v29 bots/<name>`, flip the switch, `cambc build <name>`), then run
  `tools/ab.py` on all 40 maps, both sides. Accept only on the **sum over the field bots**
  (zmeta, zpoke, zhor, zrush, zdive0, zgank) and never on the mirror alone.
- Some failures only show on the ladder (contest feeding, pick-offs). Build an adversary that reproduces
  the ladder pattern before trusting a local result.

Part 1 (C1-C6): fixes from the ladder analysis. Part 2 (C7-C9): ideas from the v2.5.0-python bot.
Part 3 (R1-R7): research-based design items. The combined order is in "Updated priority order"
near the end.

---

## C1. `CAMP_DANGER`: treat awake camps as danger when walking (bug fix, highest priority)
**Evidence.**
- On 01starfish as side B, ladder-v27 died 54 times a game, 15 of them killed by the camp itself,
  against 14 different opponents. As side A it is about 3 a game.
- Locally v28 shows the same: 40-53 deaths as side B vs 9-14 as side A (vs zmeta/zdive/zpoke). Our
  engine-based opponents die 50+ times whenever they are on side B.
- Replay: a full-HP, 0-gem champion walks alone past elks someone else already woke (HP below max),
  (29,20) → (25,20), and is at 4% HP four rounds later. Starfish's only two altars, (23,17) and
  (26,17), sit inside the 6-elk, 118-gem centre group (reach 4).

**Cause.** `Bot::ensure_danger()` (bot.cpp:918) and `burst_at()` (bot.cpp:935) only score enemy
champions and remembered enemies, so `move_to()` (bot.cpp:371) never routes around an awake camp.

**Change.**
1. In `observe()` (bot.cpp ~255, where `live_hp` is summed), also record per group whether it is
   awake: any visible living camp with `health() < base health`, or the group damaged us last turn.
2. In `ensure_danger()`:
   - For each awake group that is **not** our current target (and that we are not capturing or
     attacking this turn), set `square(camp position, camp reach)` in `danger` for every living
     fighting camp (strength > 0).
   - The early return `if (peak < limit) return;` must not skip this step, so add the camps' summed
     strength to `peak` or run the camp pass before the return.
   - Clear `danger` on our own tile and on `goals`, as the code already does.
3. Optional second step (separate switch `CAMP_DANGER_SLEEPING`): also avoid the reach of sleeping
   groups whose total strength would kill us within ~3 rounds. Only if C1 alone leaves starfish deaths high.

**Test.**
- First 01starfish both sides vs zmeta/zpoke/zdive (target: side-B deaths from 40-53 down to the
  side-A level).
- Then the full pool vs the field bots, plus a mirror vs v29.
- Watch for longer routes making bank trips slower (avg win round) on altar-in-camp maps (starfish,
  hooks, shortcut, broken_curve, boss_battle).

---

## C2. `TEAM_CLOSEOUT`: bank everything when the team total wins
**Evidence.**
- In 32 ladder losses (outside boss_battle), our tributed plus carried gems were already ≥ 1000,
  typically ~40 rounds (6-217) before the enemy hit 1000.
- The gems were spread over several 30-80 gem bags. v28/v29's "winning bag banks first" rule
  (bot.cpp:1763, 2240) only fires when a single bag wins on its own. That is 5% of losses, so up to
  about +2.8% win rate.

**Change.**
- In `should_bank()` (bot.cpp:1759), before the `BLOCKED_ALTAR_FARM` embargo check, compute the
  team total: `global_submitted_gems(ally) + my bag + the bags of visible allies` (`mates[].gems`).
- If the total reaches `winning_gems`, return true for any bag ≥ `CLOSEOUT_MIN_BAG` (10). Treat it
  like the winning-bag rule: it ignores the embargo and the mid-camp/fight gate in `farm()`
  (bot.cpp:2241, `wins_now`).
- Allies are often out of vision. Variant B (`CLOSEOUT_BROADCAST`) uses shared-memory byte 7
  (free since HELP_CALLS is off). Each body writes its bag in 16-gem buckets into a 2-bit slot,
  or byte 7 carries a "close-out now" flag. Whoever computes total ≥ 1000 sets it, and every carrier
  that reads it banks.
- Variant C (`CLOSEOUT_MARGIN`, e.g. 150): once `global_submitted_gems(ally) ≥ 1000 - margin`,
  every bag ≥ 10 banks, with no knowledge of allies' bags needed.

**Test.** Full pool vs the field bots. Extra metrics: number of games won with `sub` exactly reaching
1000 earlier, and avg win round. Earlier local "close-out" ideas were neutral, so judge on the field
sum. Ladder re-check: the count of "held a winning team total" losses.

---

## C3. `BOSS_ALTAR_OPEN`: re-enable banking the moment the boss dies (01boss_battle)
**Evidence.**
- 01boss_battle has one altar, at (25,20), and every tribute tile is blocked by the 400-gem boss
  monolith camp. Opponents killed the boss first in most games and then tributed straight away.
- In 5 losses we sat on 700-3900 carried gems and never tributed. 13 of 39 games on the map are
  losses.

**Cause.**
- When `bank()` fails it sets `bank_blocked_until = round + BLOCKED_ALTAR_ROUNDS (25)`
  (bot.cpp:1857, 1935).
- `should_bank()` then returns false until that expires (only a single winning bag overrides it).
- So when the boss dies, our carriers keep farming for up to 25 rounds and are spread over the map.

**Change.**
1. When a group that blocks tribute tiles (record at init the groups whose spawn tiles overlap the
   tribute squares) is seen dead, or its capture is broadcast in byte 6, set `bank_blocked_until = 0`.
2. While banking is blocked and we carry ≥ `BOSS_RUSH_BAG` (e.g. 100), hold within ~8 tiles of the altar
   instead of farming far away, so we tribute first when it opens.
3. Optional: kill the boss ourselves when our team carries enough to win (`team bags ≥ 1000 - enemy
   lead`). It needs most bodies: 400 gems, about 40k HP, strength 200, reach 5.

**Test.** boss_battle both sides vs all adversaries, plus an adversary that kills the boss (C4's
`zmono2`). Check that the rest of the pool is unchanged (only this map has blocking groups).

---

## C4. Monoliths: stop conceding them
**Evidence.**
- Per game we take 4 monolith gems and opponents take 41. Golems go our way, 34 vs 14.
- Opponents' take per game: contest 467, gold_rush 322, boss_battle 277, monolith 94, broken_curve
  67, starvation 59, big_world 44, fracture 40, rows 40.
- On maps with a monolith our win rate is 31% when the opponent takes one, against 53% when nobody does.
- Earlier tests (MONOLITH_WHEN_DOMINANT, VULTURE) failed against copies of our own bot, which never
  take monoliths first. The ladder field does take them, so those tests could not show the cost.

**Change.**
1. Build an adversary **`bots/zmono2`**: v29 with `MONOLITH_FIGHTS = true` (and/or
   `MONOLITH_WHEN_DOMINANT`), so it takes monoliths like the ladder field does. Confirm locally that
   v29 loses monolith gems to it the way it does on the ladder.
2. Candidates on v29, each behind its own switch:
   - `MONO_VULTURE`: VULTURE (bot.cpp:601) restricted to monoliths. Finish an enemy-softened
     monolith below `VULTURE_HP_FRAC`, or contest its capture tile when an enemy is on it.
   - `MONO_QUIET`: allow monolith fights when no enemy has been seen for N rounds and ≥ 3 bodies are
     within the wait ring (`MONOLITH_MAX_NEED` is 2 today).
   - `MONO_ONLY_MAPS`: on maps where every gem group is a monolith (contest; the lazy `mono_only`
     already exists), commit to monoliths from the start.

**Test.** Monolith maps vs zmono2 and the field bots. Accept only if the field sum does not drop.

---

## C5. Gem-dead maps: stop feeding kill gold (00contest, 00stampede)
**Evidence.**
- 19 of the 87 ladder losses at round 2000 were 0-0 ties decided on gold, 15 of them on contest.
- In those games we die 55-90 times against their 0-9, which puts their gold at 12-23k against
  our 3-8k (kill gold 100).
- About 7 deaths a game happen at our own spawn: we get spawn-camped.
- Locally contest is a win, and the old `ZERO_FEED` was harmful against zmeta. Do not reuse it.

**Change (needs an adversary first).**
1. Build an adversary **`bots/zspawn`**: v29 plus hunters that sit near the enemy spawn on gem-dead
   maps. Reproduce the ladder death counts locally before testing anything.
2. Candidate `SPAWN_REGROUP`: after a respawn, when an enemy (seen or remembered) is within ~8 of
   our spawn exit, wait on the spawn tiles (healing, shopping) until ≥ 2 allies are with us, then
   leave together. Once deaths in the last 100 rounds pass N, use the gold-tiebreak mode. In it,
   farm only groups with no enemy seen nearby and break off a fight when it is even.
3. C4's `MONO_ONLY_MAPS` makes contest gem-live, which may matter more than C5.

**Test.** contest and stampede both sides vs zspawn and the field bots, plus the full pool for side effects.

---

## C6. Invasion and capture theft
**Evidence.**
- On lanes, collision and monolith each side farms its own half about equally, but enemies kill us on
  our own half 4-5 times as often as we kill them.
- Across all games they steal 23 gems a game from our clears, against our 14. The worst maps are
  elk_arena 105, corridors 98, starvation 49, elkring 28, lost_world 26 and lanes 23.

**Plan.**
- **Measure first.** v29's CONVERGE (join a teammate's fight when side power favours us) targets
  exactly these deaths. Once v29 has 300+ ladder games, rerun the pattern scripts (below) and
  compare deaths-on-our-half and theft per map against ladder-v27.
- **Only if still bad,** candidate `CAPTURE_GUARD`: when an enemy is within 6 of a capture we are
  holding, the nearest ally within 8 converges on the capture region instead of continuing to farm.
  The earlier CAPTURE_CONTEST and CAPTURE_ASSIGN variants were rejected; this one differs by moving
  a second body rather than having the capturer fight or leave.

---

---

# Part 2: ideas from v2.5.0-python (our old Python bot)

Source: `v2.5.0-python.zip` (repo root; read, never run). It is a 3-layer design: emergencies, scored
objectives with hysteresis, then execution, plus a belief model and EV banking. v29 already covers or has
outgrown most of it (commitment, lane spread via claims, winning-bag banking, lock interrupts and
breaking, draft memory). Three ideas are worth carrying over.

## C7. Camp-reach avoidance while walking (Python `nav.py::_dangerous`): merge into C1
The Python bot refuses any step inside the attack range of a camp with strength > 0. This is the same
fix as C1, and it confirms the approach. Keep C1's narrower rule (only awake camps that are not our
target): the blanket version would block approaches to every camp we want to farm. Implement as part
of C1 and test as one switch.

## C8. `PRIORITY_ORDER`: use `set_priority()` to order our own turns
**Mechanic.**
- GameRules "Who goes first?": teams alternate champion by champion, and the starting team swaps
  every round.
- Within a team, higher priority acts first. `self().set_priority(int)` takes effect from the next
  round and persists.
- v29 never calls it, so our order is the draft order.

**Change.** At the end of every `play_turn()`, set next round's priority from this turn's state:
- highest: in a fight or under threat (`burst_here > 0`, or a foe within 4), and hurt carriers. They
  strike or escape before the enemy's next champion acts.
- next: champions that write shared memory (capture broadcast, a new claim, close-out flag C2),
  so teammates read the message **in the same round** instead of one round later. This speeds up
  CONVERGE and claims.
- lowest: champions farming quietly far from enemies.

Priority is scored like the Python bot's `10 + gems - hp-loss`, but driven by threat. Keep the value
stable while nothing changes, so the order does not churn.

**Test.** Full pool vs the field bots and a mirror. Expect gains in PvP-heavy games (zdive0, zgank,
zpoke). Check that equal-strength fights now go our way more often (deaths for/against).

## C9. `STATIC_OWNERSHIP`: label camps and altars from spawn geometry at init
**Python `mapinfo.py`.**
- It runs distance fields from both spawns.
- A camp group is ours when `ally_dist + 2 < enemy_dist`, theirs on the reverse, contested otherwise.
- An altar is "safe" when we reach it at least 1 tile earlier than the enemy.
- v29 learns safety only from sightings (`altar_hot`) and has no ownership notion.

**Change.**
- In `init()`, compute `enemy_spawn_field` (one extra full-map field, about 2-11K fuel, on the first
  turn's budget).
- Store per group `owner ∈ {ours, theirs, contested}` and per altar `static_safe`.

Uses:
1. `bank()`: prefer `static_safe` altars when the bag is ≥ the threat-bank size (tie-break today is
   distance only).
2. C6 `CAPTURE_GUARD` / invasion defence: only guard our-owned and contested captures.
3. Map features for R4 (macro plan): share of gems on our half vs contested.

Alone it should be close to neutral. It is infrastructure for C6 and R4, so test it with them.

---

# Part 3: research-based items

Each item names the work it comes from, the loss pattern it targets, and how it plugs into v29.
Bigger than C1-C9: these are design changes for v30+, roughly in order of expected value per effort.

## R1. One shared danger / influence map (potential fields)
**From:** Hagelbäck & Johansson 2008, multi-agent potential fields in RTS; Tozour 2001, influence maps;
Uriarte & Ontañón 2012, kiting with influence maps.
**Targets:** isolated pick-offs. 78% of our ladder deaths are isolated and 97% untraded, and
"allies within 8 but not 4" is the typical setup. It also covers C1 (camps).
**Change.**
- Replace the boolean `danger` bitboard in `move_to()` with a small float cost per tile around us
  (radius 4-6), the sum of:
  - enemy burst (existing `burst_at`)
  - awake-camp damage (C1)
  - remembered-enemy burst
  - an **isolation cost**: + k for every tile farther than 4 from the nearest ally, applied only while
    an enemy or ghost is within ~10
- Pathing minimises distance + λ·cost instead of hard-avoiding tiles. With it OFF, behaviour reduces
  to today's (λ = 0, threshold kept).

**Test.** The local field bots under-punish isolation (see LadderPatterns). Build an isolation
hunter first (zgank exists; extend it to go only after lone targets), then the full field.

## R2. Fight prediction with fitted Lanchester exponents and a small portfolio search
**From:** Stanescu, Barriga & Buro 2015, Lanchester attrition laws for StarCraft combat prediction;
Churchill & Buro 2013, portfolio greedy search.
**Targets:** fights we take and narrowly lose. Ladder replays show HP drains over 10 rounds while we
outnumber 42% of the time.
**Change.**
1. `side_power()` today = Σ HP × dps with `OUTMATCHED = 1.25`. Fit the Lanchester exponent and
   per-champion effectiveness from logged local fights: a regression on (our/their HP, dps, stuns,
   dash) → winner. Use the fitted model as the outmatched test.
2. For skirmishes with ≤ 3 v 3 bodies within 6, simulate 3-4 scripted policies for ~5 rounds and
   pick the best outcome. Policies: focus the lowest HP, focus the carrier, kite, disengage to the
   nearest ally. The old `simulate_fight()` already exists as the forward model.
   Budget: < 15K fuel per call.
**Test.** Deaths and kills in PvP vs zdive0/zgank/zpoke, and the field sum.

## R3. Deterministic team task allocation (CBBA / Hungarian assignment)
**From:** Choi, Brunet & How 2009, CBBA (consensus-based decentralised task allocation); Kuhn 1955,
Hungarian method.
**Targets:**
- theft: 23 vs 14 gems a game, elk_arena 105, corridors 98
- greedy claim collisions
- nobody guarding captures or escorting carriers
**Change.**
- Every champion runs the same assignment on the same inputs: positions of allies in vision,
  claims from shared memory, and static geometry. It produces a matching of bodies to tasks: farm
  group g, guard the capture of g, escort carrier c, or close out (C2).
- Cost = travel + kill/capture time − value, with the squad `need` as a multi-body task.
- With ≤ 6 bodies and ≤ ~20 candidate tasks, the Hungarian method is cheap (O(n³) on a 6×20 matrix).
- Ties break by body index, so every teammate gets the same answer without messages. That is the
  same idea as today's `capturer()`, generalised.
- This replaces `choose_target()`'s independent greedy pick; keep the old path as the fallback.

**Test.** Full pool, the field sum, and theft per game in the local stats. Old note: the TOUR_PLAN
beam search (multi-group routes) failed at 11/70; this is single-step assignment, not routing.

## R4. Macro layer: a map-aware plan from the draft turn, updated by score state
**From:** Wu et al. 2019, "Hierarchical Macro Strategy Model for MOBA Game AI" (Honor of Kings).
It predicts phases and the regions to focus on, and micro play carries them out.
**Targets:** the 7%-97% win-rate spread by map. Today the bot plays one rule set everywhere.
**Change.**
1. Draft turn (1M fuel): compute map features with C9. Features: monolith gem share, golem share,
   altars inside camp groups, altar count and centrality, contested-gem share, gems-per-1000-rounds
   supply, gem-dead flag, 3/4/5 bodies. Store a mode byte in draft memory.
2. Modes: `FARM_RACE` (default = today), `MONOLITH` (C4 plays), `HOLD_HALF` (defend our-half camps,
   C6), `GOLD_TIEBREAK` (gem-dead maps, C5), `ALTAR_IN_CAMP` (C1 routing, bank only when the group
   is asleep or dead). The modes only change weights, thresholds and switches; no map is named.
3. In-game switches by score state: `CLOSE_OUT` (C2), `DENIAL` (exists), and `CATCH_UP` (when
   behind by more than X with the enemy close to 1000, contest their altar or carrier).

**Test.** Mode by mode against the maps it targets, then the full pool. Every mode must be no
worse than `FARM_RACE` on the maps it does not target.

## R5. Particle belief for unseen enemies
**From:** Weber, Mateas & Jhala 2011, particle model for state estimation in RTS games.
**Targets:**
- carriers walking into enemies we cannot see
- the gank/ambush deaths in "open" ground
- altar safety
**Change.**
- Replace ghost tracking (one decaying point per vanished enemy) with ~8 particles per enemy.
- Each round, particles step one tile along legal moves, biased toward the camp groups, altars and
  our carriers that the enemy is likely heading for.
- Particles in our vision that see nothing are removed, and the set is resampled when the enemy is
  seen again.
- The particle density feeds R1's cost map and `SAFE_ALTARS`.
- Fuel: 6 enemies × 8 particles × 1 step is negligible. Only the vision pruning costs, as bitboard ops.
**Test.** Deaths while carrying ≥ 20, bag losses per game, and the field sum.

## R6. Automatic tuning (CLOP or SPSA) and SPRT-stopped A/Bs
**From:** Coulom 2011, CLOP (confident local optimisation for noisy black-box tuning); SPSA; Wald
1945, the sequential probability ratio test (SPRT), as used by Stockfish's fishtest.
**Targets:**
- 100+ hand-tuned `Cfg` constants
- many A/B verdicts within ±5 wins of baseline (noise), so real small gains get rejected and noise
  gets shipped
**Change (tooling only, no bot logic).**
1. `tools/sprt.py`: run games in batches of 16 (`run-batch`) and stop when the
   log-likelihood ratio crosses the bounds for H0: Δ ≤ 0 vs H1: Δ ≥ +2% (α = β = 0.05). Run it over
   the field bots, alternating sides and maps.
2. `tools/tune.py`: SPSA over a chosen set of 4-8 constants (`OUTMATCHED`, `BANK_BAG`,
   `PVP_BANK_BAG`, `DANGER_TILE`, `RETREAT` HP, R1's λ and isolation k). Use compile-time overrides
   (`-D` flags into `Cfg`) so each candidate is a build. Accept the tuned set only through SPRT.
**Cost.** CPU time: about 10 s per game, 8 in parallel.

## R7. Banking as optimal stopping (expected loss vs forgone farm)
**From:** optimal stopping with a loss hazard; the Python bot's `economy.bank_pressure` is a rough
version.
**Targets:** fixed bag thresholds (`BANK_BAG` 48, `PVP_BANK_BAG` 30, and so on) that ignore how risky
this tile is right now. 163 carried gems are lost per game in the ladder losses.
**Change.**
- Bank when `bag × P(lose bag before the next bank opportunity) > farm rate × (travel + channel
  rounds)`.
- P comes from R1/R5's danger along the path to the altar plus the current HP share. The farm rate
  is the team's recent gems per round.
- Keep the winning-bag (v28) and close-out (C2) rules as hard overrides.
**Test.** The field sum, bag losses per game and avg win round. It must not reintroduce tiny-bag
tributes (the old detour-banking lesson).

---

## Updated priority order
1. **C1 + C7** (camp danger): reproducible bug, cheap.
2. **C8** (`set_priority`): cheap, untested mechanic.
3. **C2, C3** (close-out, boss altar): wins left on the table.
4. **R6** (SPRT tooling): makes every later A/B cheaper and more trustworthy. Build it before the big items.
5. **C9 → R4** (static ownership → macro modes), with **C4** (monoliths) and **C5** (gem-dead) as the
   first modes.
6. **R1** (influence map with an isolation term), with **R5** (particles) feeding it.
7. **R3** (assignment), then **C6** (guards) on top of it.
8. **R2, R7** (fight prediction, optimal-stopping banking): after R1/R5 exist, since both read the
   danger map.

Before Sprint 3 locks (31 Oct): realistically items 1-4, plus whatever of 5 passes SPRT.

## Measurement pipeline (re-run after each ladder upload)
Scripts are in the session scratchpad `lad/` and should be copied into `Submission/tools/` if kept.
- `pull.py`: lists new ranked matches into `rows.json` (tag the era by upload time).
- `dl.py`: downloads summaries, 4 threads with backoff.
- `ev.py`: builds per-game event records.
- `pat.py`: map table with win rate, distinct opponents and collected/deaths/gold.
- `pat2.py <maps>`: per-map gem flow by group, death zones with killer (champion or camp), theft.
- `cross.py`: monolith/golem gems, camp deaths, theft and bag losses per map.
- `miss.py` / `held.py`: losses with a winning team total, and 0-0 tiebreak losses.

Map geometry comes from `bots/zgeo`, a probe that prints groups with per-camp positions, altars, spawns
and terrain, 4 lines per turn. Run `cambc run zgeo zidle --map maps/<m>.map26a --rounds 100 --release`
and read `team-a.stdout` from the replay. Side A = `SPAWN_A`.

## Ship checklist
1. Every new switch OFF: the build is bit-identical to v29 on all 40 maps × 2 sides vs at least zmeta.
2. Accepted switches ON: the field sum beats v29, no bot faults, and the mirror vs v29 is ≥ 50%.
3. `kessoku.zip` has exactly the 6 src files (no "… 2" duplicates), and an unzipped copy builds.
4. Hand the zip to the user to upload (never `cambc submit`).
