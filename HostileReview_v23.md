# Hostile review of `bots/kessoku` v23 (2026-10-21)

Scope: all of `bot.cpp`, `bot.h`, `common.h`, `draft.cpp`, `main.cpp` (zip = source, verified identical), plus 180 ranked ladder games played by v23 (draft Vesper/Tavi/Willow opening, 19:30 UTC 20 Oct onward) and 35-map local sweeps.

Labels: **CODE** = read in source; **LADDER** = computed from `cambc matches summary` of 180 games; **MEASURED** = local deterministic A/B (`tools/ab.py`, 35 maps x both sides = 70 games, parity 35); **HYPOTHESIS** = untested.

Caveats: the "field proxy" opponent `zmeta` is kessoku logic with the ladder's dominant comp (Stellar, Ren, Varg, Ryth, Cassi & Issac). It is not a real opponent, but it reproduces the ladder (v23 beats it 43/70 = 61%; ladder 57%) and its weak maps (contest, corridors, starfish). Matches are deterministic, so each number is exact for that pairing but small-sample as a predictor. Ladder opponents differ from it.

## Ladder baseline (v23, 180 games)

- 103-77 (57%). Old draft era: 54%. 5-pick maps 67-45, 4-pick 23-17, **3-pick 13-15** (n small).
- Wins vs losses: we collect 1142 vs 590 gems; our deaths 13 vs 31; our K:D overall 6.3 kills vs 15.7 deaths-to-champions per game.
- **Deaths are the swing.** Losses average 2.96 "wipes" (3+ of our bodies dead within 12 rounds) vs 0.83 in wins. 21 deaths a game x 60 rounds = 14% of all body-time (21% in losses).
- We lose 121 carried gems a game to deaths (handed to the killer): 422 deaths with bag >= 20 cost 17,749 gems.
- Worst maps: 00contest 1-6 (74 deaths/game), collision 1-5, elkring 1-5, rushbait_v2 2-5, reverse_spiral 2-5, packs 1-3, eight 2-4.

## Findings

### 1. Stat build is all damage, no health (MEASURED + LADDER) -- biggest

- **Where:** `Bot::next_item()` (`bot.cpp:295`). After the Monster + Jungle emblem plan it returns `power_shard_of_strength` (or Focus) forever.
- **Mechanism:** Ladder: 172 Power Strength shards a game, 0 health. Estimated end-of-game Vesper: **690 Strength, 1385 HP** (field Ryth 3209 HP, Varg 1856, Stellar 1233 with 547 Focus). Fight power is HP x damage; with base HP/growth equal to base Strength/growth (Vesper 900/100 vs 45/5), equal shard counts keep the ratio, so strength-only shards drive it badly out of balance. One Stellar or Ren burst kills a 1400-HP glass cannon.
- **Exploit:** any bruiser comp that closes distance. Field deaths: Stellar 799, Ren 475, Cassi 332 kills on us.
- **Frequency:** every game.
- **Fix (6 lines, in `kessoku_v23_review_fixes.diff`):** `Cfg::HEALTH_PCT = 100`: buy Power Health shards in step with Power Strength/Focus shards.
- **Result (MEASURED vs `zmeta`, 70 games):** 0% -> 43; 50 -> 54; 100 -> 54; 200 -> 51; 400 -> 50. Mirror vs live v23 with 100: 45/70, deaths 903 -> 762. Vs the ranged-poker bot `zpoke` (with finding 2): 34 -> 49.
- **Regression test:** `ab.py` new-vs-old on all 35 maps, plus `zmeta`. Pass: >= 40/70 mirror, deaths down, no map group loses more than before.

### 2. Cassi & Issac are the worst champion per body (LADDER + MEASURED)

- **Where:** `draft.cpp:41`, `PAIR_DRAFT_SCORE = 9.6` (4th pick).
- **Mechanism:** Pair dies 5.47 times a game (52% of our body-deaths), Issac deals 857 champion damage a game and takes 4,870; 0.18 kills. One death removes both for 60 rounds. v21 tuned retreat to 50% but the ladder rate is unchanged.
- **Fix:** `PAIR_DRAFT_SCORE = 7.0` (the draft then takes Varg + Stellar).
- **Result:** alone vs `zmeta` 55/70 (deaths 601 vs 889), vs mirror 38/70. Combined with finding 1 (`kc1`): **zmeta 59/70, mirror 44/70, zpoke 49/70 (was 34), zhor 56/70 (was 49), zcamp 70/70, zlock2 65/70 (was 64), oldpy 70/70, starter-cpp 70/70**. The clean patch reproduces 59/70 exactly.
- The earlier note "pair never drafted: 15/42" was measured in the pre-3.0 meta; it does not hold now.
- **Regression test:** same sweep; pass if `zmeta` >= 55/70 and `zpoke` >= 45/70.

### 3. Piecemeal feeding into held zones (LADDER, fix NOT found)

- **Where:** `DEATH_AVOID` (`play_turn`, dead branch) is per-instance state (`groups[].skip_until` lives in each champion's own `Bot`), covers groups within 4 tiles of the death and lasts 150 rounds. Shared byte 7 (`Mem::HELP`) is unused.
- **Evidence:** 00contest ladder games: 56-110 deaths, one body died 21 times, median 84-124 rounds between deaths, deaths concentrated at three central 80-gold groups. Locally `zmeta` reproduces it (kbase 0/2 on contest, 56-59 deaths).
- **Tested fix:** share the death group through byte 7 so every ally skips it for 150 rounds: **39/70 vs zmeta (was 43), 31/70 mirror -> worse.** Not recommended. Findings 1-2 cut contest deaths more.
- **Accidental defence:** `DEAD_CLEARS_CLAIM = false` leaves a dead body's claim set, which halves that group's value for allies (this is probably why clearing it measured worse in v19).
- **Open idea (HYPOTHESIS):** when 2+ bodies are dead, farm only groups within N tiles of spawn; test on contest/rows/starfish.

### 4. Carriers die near altars and camp fights (LADDER; fixes neutral)

- 63 deaths with bag >= 20 within 2 tiles of an altar (3,364 gems), 84 within 3-6 tiles (4,403), 190 within 4 of a camp group (6,991). 44% of lost gems are altar-area.
- **CODE:** `bank()` (`bot.cpp:1599`) calls `submit_gems` with enemies adjacent; the channel lasts `ceil(bag/10)` turns, `play_turn` returns early while channeling, and the only lethality test (`burst_here * 1.15 >= my_hp`) covers one turn. Damage does not stop a tribute, death does. The cause of the altar-area deaths (channel vs approach) cannot be separated from summaries.
- **Tested:** refuse to start a tribute when 6-tile enemy dps x channel turns >= HP (`TRIBUTE_SAFE`): 43/70 vs `zmeta` (unchanged), 36/70 mirror. Bank at 50 even mid-fight (`FIGHT_BANK_BAG`): 41/70, 33/70 -> worse. So the mechanism exists but these fixes do not move results; carrier loss is mostly a symptom of finding 1.

### 5. Retreat and fight-margin thresholds (MEASURED, minor)

- `RETREAT_HP` 0.40: 46/70 vs `zmeta`, 32/70 mirror. `FIGHT_HP_MARGIN` 0.35: 44/70, 38/70. On top of finding 1+2: retreat 0.40 gives zmeta 53/70, mirror 40/70, zpoke 53/70 (mixed). Not shipped.

### 6. Draft opening is fixed (LADDER; hypothesis for exploit)

- Same 3-5 picks in 180/180 games (Vesper, Tavi, Willow, Varg, C&I). Picks are revealed live, so a counter-drafter can plan against it. Willow is the weakest body (4.16 deaths, 0.70 kills; end Focus 105 so her 3x Focus heal is ~315 for the whole game). Replacing Willow with Stellar: 49/70 vs `zmeta`, 36/70 mirror (modest); with finding 1+2 it was worse (48/70). Keep the opening until a real counter-drafter appears.

### 7. Smaller code defects

| # | Item | Label | Note |
|---|---|---|---|
| a | `should_bank` end-game bank starts at `round + 40` (`bot.cpp:1530`), ignoring walking distance | CODE | Distance-aware version (`END_BANK_DIST`) 44/70 vs `zmeta`, 36/70 mirror = neutral. 33/180 ladder games reach round 2000; none flipped by it. Low priority |
| b | `paid` treats any gold jump >= 10 as a capture (kill bounty is now 100 gold) | CODE | Known (F7b), switch measured worse |
| c | Wards never placed; opponents place 236 a game | LADDER | Benefit untested |
| d | Monoliths never fought (`MONOLITH_FIGHTS = false`); monoliths hold >= 59% of gems on 8 maps and 100% on contest | CODE | Opponents tribute 400-1000 gems there. Forcing monolith fights ("zmono") did not beat v23 locally (12/16), so no fix yet |
| e | `draft.cpp` writes an "opening plan" to draft memory that no gameplay code reads | CODE | Dead code |
| f | 01yellow_brick_road game b9de5400: both teams 0 gold, 0 gems; we lost on the "Team B wins" tiebreak with 161 fuel-exhausted events | LADDER | Single anomaly, unexplained |

## Adversarial opponent archetypes

| # | Archetype | Targets | Status |
|---|---|---|---|
| 1 | **Bruiser dive**: Stellar + Ren + Varg + Ryth (+C&I), stat-balanced, walks into glass cannons | Finding 1, 2 | Proxy `zmeta`; v23 43/70, 0/2 on contest/corridors/starfish/the_farm/lanes/rows... |
| 2 | **Central holder**: whole squad parks on the middle gold groups and kills each body as it respawns | Finding 3 | Seen on ladder contest; proxy `zmeta` on contest |
| 3 | **Altar sniper**: stun/burst carriers on the last 3 tiles or during the tribute channel, wards on the altar | Finding 4 | Not built |
| 4 | **Ranged kiter** (Vesper/Tavi/Willow, move-reset-attack) | melee chase logic | `zpoke`: v23 34/70, fixed build 49/70 |
| 5 | **Locksmith** (locks every altar) | lock clearing | `zlock2`: 64/70 v23, 65/70 fixed (already patched in v19) |
| 6 | **Altar camper** | altar flip-flop | `zcamp`: 70/70 (patched in v19) |
| 7 | **Monolith rusher / counter-drafter** | Findings 6, 7d | Counter-drafter not built; rusher variant did not beat v23 |

## Ranked top five and fix order

1. **Stat build with no health** (finding 1). Apply `kessoku_v23_review_fixes.diff` hunk 1. Biggest measured gain (43 -> 54 of 70 vs the field proxy).
2. **Cassi & Issac draft score** (finding 2). Hunk 2 of the same diff; combined 59/70 vs field proxy, 44/70 mirror, no regression on 6 other opponents.
3. **Piecemeal feeding when bodies are dead** (finding 3): needs a different fix than shared death memory (that one measured worse).
4. **Carrier exposure at altars** (finding 4): real losses (44% of lost gems) but the two cheap fixes were neutral/negative; revisit after 1-2 are live and re-pull ladder data.
5. **Fixed, revealable draft / Willow** (finding 6): wait for evidence of counter-drafting; test Willow replacement again after 1-2.

Order: ship 1+2 together (patch applies cleanly: `git apply kessoku_v23_review_fixes.diff`), rebuild `kessoku.zip`, upload, then re-pull 100+ ladder games and compare deaths/game (21 now) and wipes/game before touching 3-5.

## Artifacts

- `kessoku_v23_review_fixes.diff`: findings 1 + 2, not applied to `bots/kessoku` or `kessoku.zip`.
- Temporary test bots were deleted. Ladder summaries and the aggregation scripts are in the session scratchpad only.

## Re-measurement on cambc 3.0.4 (balance patch: Stellar/Ren/Heart of Ruin nerfs, Vesper/Tavi/Vendetta HP buffs)

SDK refreshed (`pip install -U cambc==3.0.4`, `cambc init --yes .`; the live v23 still compiles unchanged). A probe confirmed the engine has the new stats (Stellar 650 HP / 70 Focus, Vesper 1000 HP / 55 Strength, Tavi 900 HP / 110 Focus). The pool is now 45 maps, so 90 games per pairing (parity 45). Opponents were rebuilt on the new SDK.

| Opponent | live v23 | health shards only | pair demotion only | both (the diff) |
|---|---|---|---|---|
| field-comp proxy (`zmeta`) | 65 | 73 | 72 | 69 |
| live v23 (mirror) | - | 56 | 49 | 56 |
| ranged poker `zpoke` | 45 | 53 | 49 | **62** |
| Heart of Ruin bot `zhor` | 71 | 74 | - | **77** |
| locksmith `zlock2` | 81 | 83 | - | **85** |
| camper `zcamp` | 90 | - | - | 90 |
| starter-cpp | 89 | - | - | 88 |

- The gains shrink, as expected after the Strength-champion HP buffs, but the diff still wins or ties every pairing (starter-cpp 88 vs 89 is noise). Deaths vs the field proxy 752 -> 436.
- Health shards are the robust part. Pair demotion adds little alone (mirror 49/90) but the combination is best against the ranged and Heart-of-Ruin bots. Total over the five contested pairings: both 349, health-only 339.
- Not re-run on the new engine: the failed experiments in findings 3-6. Draft scores (Stellar, Vendetta) have not been re-tuned; Vendetta at 1000 HP is the obvious thing to try next.
