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

Priority order: C1 → C2 → C3 → C4 → C5 → C6.

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
