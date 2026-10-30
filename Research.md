# kessoku research notes

One place for everything learned about `bots/kessoku`: ladder evidence, engine facts, every measured
experiment, open ideas and testing method. It replaces AlgorithmReview.md, ForensicReasons_v22_v23.md,
ForensicReport_ladder_v22_v23.md, LadderPatterns_v27.md, Maps_Analysis.md, MetaResearch_v25.md,
PerformanceAudit.md, Plan_v29.md and StrategyResearch.md (all still in git history, last at commit `cb77166`).
Rules and API: `GameRules.md`, `BotAPICpp.md`. Commands and bot layout: `Submission/SUBMIT.md`.

Labels: **RULE** = GameRules.md; **PROBE** = confirmed by a scripted local bot; **LADDER** = ranked-game
summaries or replays; **MEASURED** = deterministic local A/B; **THEORY** = untested.
Version names are internal (the ladder numbers its uploads one lower until v28: ladder "v27" = internal v28).

---

## 0. Patch 2026-10-26: engine 2.0.0 / cambc 4.0.0

- Breaking: the item backpack grew from 42 to 84 item types. Bots built against the old SDK do nothing on the new engine
  (0 gold, 0 damage, no error, no fault). After upgrading cambc, run `cambc init --yes .` in Submission/ AND delete every
  `bots/*/.cambc` build cache, or `cambc build` keeps the stale build. The sprt cache is now keyed by `cambc --version`.
- Map pool 40 -> 70 maps (new 00anvil/breadcrumbs/crater/dunes/galaxy/oasis/quarry/ribs/the_line/vault, 15 `02*` maps,
  adgato_gemcombat1-5); the list is in `Submission/tools/data/pool.txt`, used by tools/sprt.py and tools/ab.py.
- Balance: Treasure +20% -> +10% gold; Monster +10% -> +15% camp damage; Vesper Strength 55 -> 45; Varg 40 -> 45; Tavi
  stun 1.4 -> 1.6x Focus; Willow Focus 120 -> 140; Marcella/Ryth Strength per shard 5 -> 4.5; Heart Strength/Focus per shard
  down; Cassi, Stellar, Prism, Ren, Issac up. Draft first-turn fuel x10.
- New emblem families: Capture (capture 5 -> 3 turns when any capturer owns it), Tribute (-33% tribute time), Prospector
  (+25% cluster gold/gems), Hunter (+50 gold per champion kill), Skirmish (+5% damage to champions), Greed (25 shards ->
  35 shards of stats), Collectors (+1% damage per distinct emblem family).
- New API: camp-group `capture_state()` (ally capturing / contested / enemy capturing / available / none, with timer);
  `cambc::get_item_enum(family, stat, shard)`.
- cambc 4.0.0 now has a Linux x86_64 wheel on PyPI (at release it was macOS only, and `tools/aws_runner.py` refused to launch
  until one existed); AWS runs work on 4.0.0.
- v40pr on engine 2.0.0 after a clean rebuild: 0 faults, 24/24 vs starter-cpp, 46 vs 41 vs v36all (72 games).

## 0b. Real-opponent panel (release loop, 2026-10-26)

Workflow: limited local A/B vs the live bot -> user uploads -> `python3 tools/panel.py run LABEL` (4 unranked match groups against the fixed panel in
`Submission/tools/data/panel.json` (teams rated +100..+150 above us; same opponent versions via --source-group, maps
00eight, 00elkring, 00lanes, 01starfish, 02arena, sides a,b,a,b,a; prints a side-by-side table of all runs) -> keep
(target 40-60% wins) or roll back.
These maps are our known weak spots, so the panel is a hard test.

**Evaluation protocol (2026-10-26, against overfitting).** Panel A (above) is the *diagnostic* panel: we study its
replays to find problems, so it cannot judge fixes derived from it. Panel B (`tools/data/panel_holdout.json`) is
**held out**: 4 other band teams (Dota2 is better than LOL, team, Alpha pekka, Sic Mundus Creatus Est), 5 maps each
drawn at random from the pool minus panel A's maps (20 distinct team-map pairs), never used to design fixes, only to
accept or reject versions (`python3 tools/panel.py --panel tools/data/panel_holdout.json run LABEL`). The final judge
is ranked ladder play over 100+ games (`tools/ladder_compare.py`). Refresh panel B's teams when our rating band moves.
v47h25 on panel B: 11/20 (0/5 vs Dota2, 4/5 vs each of the other three).

| Version | Panel wins | gold@300 us/them | deaths us/them | traded | notes |
|---|---|---|---|---|---|
| v40pr (ladder v34, us 1650) | **2/20** (both on 02arena) | 920 / 1475 | 22.9 / 6.2 | 7% | starfish side B: 30-55 deaths, 13-24 of them to camps; elkring: we collect 240-680 vs 1,000+; Vendetta, Prism, Ren, Marcella top killers |
| v45sq (ladder v35) | **3/20** (arena x2, lanes vs Crimson) | 898 / 1497 | 22.0 / 6.0 | - | 12 of 20 games identical to v34 (the fix only acts on starfish). Starfish still 0/4 but camp deaths 15.5 -> 3.0 per game and we collect 498 vs 268; the remaining 30 deaths a game there are champion kills. Kept live |
| v46gc (ladder v36) | **5/20** (eight vs lETHal, lanes vs Crimson, arena x3) | 1002 / 1371 | 19.9 / 7.3 | - | elkring still 0/4 and starfish 0/4; camp deaths 1.4/game; general rules, no map gates. Kept live. Run with `python3 tools/panel.py run LABEL` |
| v47h25 (ladder v37) | panel A 4/20 (v46gc 5/20); **held-out panel B 11/20** | 1015 / 1309 | 21.1 / 5.8 | - | + HP_RATIO_GUARD: outmatched when visible enemy HP within 6 > 2.5x ours (us + allies within 6) and an enemy is within 5. From v46gc panel replays: death within 10 rounds 4% at <=1x, 26% at 1.5-2.5x, 43% above 2.5x; our deaths had enemy HP > 1.5x in 62% vs their 35%. Local vs v46gc over 820 games +93 -59 (field win rate 79.9% vs 75.3%, deaths 8.3 vs 9.6/game); panel maps 109 vs 108. K 2.0 similar (+99 -64, panel maps 105 vs 108) |
| v52pa (ladder v38) | panel A **8/20** (best yet; +5 -1 vs v47h25); **held-out panel B 6/20** (v47h25 11/20; +1 -6) | A 1048 / 1297, B 726 / 993 | A 17.1 / 7.8, B 17.1 / 7.2 | - | v47h25 + PAIR_ANYWHERE. Combined 14/40 vs 15/40: level overall, but the accept/reject panel says worse. B's lost games are mostly low-death race games (fracture, islands, the_pack, crossing): farming next to an ally costs tempo. Deaths A 21.1 -> 17.1, B 14.3 -> 17.1 |
| v55ap (ladder v40) | panel A 5/20 (+2 -1 vs v47h25), **held-out panel B 8/20** (v47h25 11/20; +3 -6) | A 1131 / 1194, B 832 / 914 | A 18.2 / 7.2, B 14.6 / 8.8 | - | v52pa + EXCHANGE_GUARD + POWER_OPENER + ALTAR_PULL. Gold@300 gap closed on both panels (A -294 -> -63, B -294 -> -82 vs v47h25) and B collects 982 vs 926, but wins do not follow; gems lost per death up 6.3 -> 10.1 on B. v39 (v54po) was live 6.5 min and played no ranked games |
| v54po (ladder v39) | panel A 6/20, **held-out panel B 8/20** (v47h25 11/20) | A 1093 / 1246, B 765 / 935 | A 19.6 / 7.8, B 14.4 / 6.9 | - | v52pa + EXCHANGE_GUARD + POWER_OPENER. All three post-v37 versions score 13-14/40 vs v37's 15/40; on B each loses vault, fracture, crossing and the_pack, which v37 won. The common change in all three is PAIR_ANYWHERE: next test is v37 + POWER_OPENER (+ ALTAR_PULL) without it |
| v57br (ladder v41) | panel A 7/20, **held-out panel B 9/20** (v39 6 and 8; v37 4 and 11) | A 1180 / 1178 (first parity), B 774 / 947 | A 16.4 / 9.0 (lowest yet), B 15.5 / 7.8 | - | v54po + WARD_SCOUT + PROSPECTOR_MAPS + TP_SHORTCUT + TEAM_CLOSEOUT + PO_BRUISER. 16/40 = best total so far (v37 15, v38 14, v39 14, v40 13); beats the live v39 on both panels, still 2 below v37 on B. B flips vs v39: won vault, big_world, elk_arena, crossing; lost interlock, gold_rush, hooks |
| v59ns (ladder v42) | panel A 6/20 (v41 7), **held-out panel B 9/20** (v41 9) | A 1177 / 1216, B 706 / 995 | A 18.1 / 8.8, B 15.0 / 7.9 | - | v57br + NEAR_SWEEP. 15/40 vs v41's 16/40: level. A collects more (863 vs 766) and wins elkring for the first time (vs Crimson), but loses eight and the uncancelables games v41 won; B flips: + the_pack, - crossing. Gems lost per death on B back up to 10.3 |
| v67 (ladder v45) | panel A 10/20, held-out panel B 9/20 (v65 11 and 11) | A 1454 / 1061, B 784 / 956 | A 15.1 / 10.9, B 16.9 / 6.5 | - | v65 + THREAT_BANK8 + RACE_SOLO + FIGHT_SIM_OUTMATCHED. 19/40 vs v65's 22: panel B rejects. Gems lost per death down (A 8.5 -> 5.5, B 10.1 -> 8.2) and A deaths down (18.6 -> 15.1), but B flips: lost fracture, hooks (61 deaths), the_pack; won islands. Roll back to v65 |
| v65 (ladder v44) | **panel A 11/20, held-out panel B 11/20** (v43 12 and 6, v41 7 and 9; best B tie with v37) | A **1445 / 1164**, B **982 / 822** (first lead on B) | A 18.6 / 9.8, B 14.8 / 9.8 (Cassi & Issac count twice) | - | v61 + CI_DRAFT + MONO_AVOID. **22/40 = best total**, accepted by panel B. B flips vs v43: won elk_arena, fracture, gold_rush, crossing, the_pack; lost big_world, islands stay lost. A: starfish 0/4 again (v43 2/4), arena 4/4 (v43 3/4) |
| v61 (ladder v43) | **panel A 12/20** (best ever; v41 7), **held-out panel B 6/20** (v41 9, v42 9) | A **1391 / 1121**, B 842 / 891 | A 11.7 / 10.5, B 11.9 / 7.4 | - | v59ns + MAP_MODES + TRACKING. 18/40 = best total (v41 16), but B drops: lost big_world (0 deaths), islands (5), crossing (9), elk_arena, won hooks. A gains are on close-spawn fight maps (elkring 2 wins, starfish 2, arena 1, eight 4/4); B losses are low-death race games, i.e. lost tempo. Gems lost per death A 14.1 |

 (2026-10-25)

- Submission: **v36all** = v35 + `LESS_WAIT` + `TREASURE_FIRST` + `BRUISER_ITEMS` (`bots/kessoku`, `bots/v36all`).
  Rollbacks: `bots/v35`, `bots/v31`, `bots/v28`. `bots/v36` = the same source with the three switches off (= v35).
- Binding constraint (section 4): **early economy** - camps cleared per alive champion and gold by round 300.
- Next constraint once that improves: **fight conversion** - 94% of our deaths are untraded.

### Version history (ladder results)

| Version | Change | Ladder | Local |
|---|---|---|---|
| v15 | C++ rewrite baseline | 106-84 | |
| v23 | ranged opening Vesper/Tavi/Willow | 57% overall, 34% in a 03:00-04:20 dip | |
| v24 | health shards, pair demotion (deaths -40%) | 42-28 | |
| v25 | cached per-group distance fields (`GROUP_FIELDS`, same decisions) | 202-193 | 271 vs 255 field |
| v26 | | 48% (680 games) | |
| v27 | 3-champion draft fix (`DRAFT3=2`) | | field 241 vs 235 |
| v28 | winning bag banks first (fix A) | 50% (1220 / 1365 games) | |
| v29 | + `STAND_SHOOT` + `CONVERGE` | 45% (100 games; suspect STAND_SHOOT) | zgank 51 vs 44 |
| v30 | v29 without STAND_SHOOT | probably never uploaded | |
| v31 | + `FIT_FIGHT` 0.20 (logistic fight model) | **51% (185 games)**, v29 48% (152) | +3 PvP, +4 field |
| v35 | + reverse_spiral standoff fix | | 243-243 vs v31 |
| v36all | + LESS_WAIT, TREASURE_FIRST, BRUISER_ITEMS (ladder "v32", live from 09:40 UTC 25 Oct) | 32-23 (58%) over 55 games, 09:40-11:20 UTC (first 25: 18-7) | 259 vs 243 (320 paired) |
| v40pr | + VESPER_STR_STACK + DUEL_STAND + PAIRING (ladder "v33", live from 11:30 UTC 25 Oct) | 3-2 after 5 games | vs v36all on 11 bots 746 vs 720 (+78 -52); head to head 47 vs 40; zmarc 51 vs 43 (vs v39ds) |
| v45sq | + BIG_GROUP_FULL_HP + BIG_GROUP_SQUAD (starfish centre group only), ladder "v35" from 26 Oct | panel 3/20 (v34 2/20) | starfish 23 vs 23 vs 12 bots with deaths 21 vs 31 on side B; other maps noise only |

---

## 2. Engine facts (confirmed)

- **Fuel** (RULE): 100k per champion per turn, each champion its own wasm instance; draft turn 10x, first play
  turn 2x; unused fuel is not carried. Running out suspends the turn, which **resumes at the same instruction
  next round** (not a forfeit). Wall clock is not limited.
- **Turn order** (PROBE): turns interleave champion by champion; the starting team swaps each round; there is
  no team "double turn". `champion::has_completed_turn()` tells which visible enemies already acted this round.
  `set_priority` works (read back one round later) but did not help (section 6).
- Visible enemies expose `remaining_channel_time()` and `is_submitting_gems()`; `global_submitted_gems(enemy)`
  is exact at any time.
- **Spawn-tile blocking** (PROBE): a body on a group's spawn tile freezes its respawn indefinitely (timer stays at
  0 for 230+ rounds; group returns ~9 rounds after the tile is free). Our own idle bodies do this too.
- **Lock timing** (PROBE): an enemy tribute lands `remaining + 1` rounds after our sighting if that enemy has
  already acted this round, else `remaining`. Placing a lock cancels the channel; tributing at a locked altar
  auto-attacks the lock; 3 basic attacks clear it.
- **Primed tribute** (PROBE + LADDER log): completion tributes the whole bag at completion, including gems from a
  capture that resolved during the channel. Start `4 - ceil(bag/10)` rounds into the hold (bags <= 30).
- **Camp trap** (PROBE): woken camps hit the nearest champion in range, so they can be aimed at a channelling
  enemy (bags destroyed by camp kills; kills credited to us when we last hit).
- **Bushes** (PROBE): an adjacent outsider cannot see or target a champion in a bush (error 42); the hider sees
  the outsider; attacking from a bush does not reveal; `move_absolute` onto an occupied unseen tile returns
  false, keeps the move, and reveals the occupant for the round.
- **Casting**: spells marked "Excludes walking" fail after a move in the same turn (Stellar ~47, Tavi ~25 lost
  casts per 6 games). Ren's, Tavi's and Prism's damage+stun spells are `is_cc()` only, not `is_damage`.
- Varg's basic attacks splash Strength onto everything within 1 of the target; Vendetta's kills (camps too)
  reset her cooldowns; spawn tiles heal to full at turn end; shared memory is 8 bytes (+1,024 read-only draft bytes).
- **Wards** are free, permanent, relocatable once per round within 2 tiles, radius 6, not shared with allies.
- **Bruiser emblem** = 5 shards of the chosen stat + 1 of each other (7 shard-equivalents per 150 gold);
  Power = 6. Treasure +20% gold (stacks additively with Vesper's 20%). Jungle -30% camp damage.
- Replays: ladder engine 1.0.3 must match the reader (cambc 3.0.4 ships 1.0.2 -> error 11). The reader drives the
  visualiser wasm from Node (`Game_FromReplayFileBytes`, `Timeline_Seek`, `ReadTimelineState`; snapshot: round u32@8,
  champions count@172 data@196 stride 252, camps count@176 data@4228 stride 28; dead camps have x = -1).

---

## 3. What decides ladder games

- **Early lead.** Collected-gem lead at r300 wins 67-80% vs 29-34% without (v23-v25); lead >= 100 tributed at
  r700 wins 88%, behind by 100 wins 10%. For v31, **gold lead at r300 is the best early predictor (AUC 0.82;
  gems 0.73, kills 0.70)**: 17% wins in the bottom gold quartile, 87% in the top.
- **Losses are blowouts** (median final margin 364 gems), decided by fights and the contested middle: in v25 losses
  we took 215 contested-zone gems vs their 440 (wins 528 vs 196).
- **Deaths**: in v28 losses 17.5/game vs 6.3 in wins, 97% untraded, 78% isolated. Replays: 10 rounds before death
  the victim is at 95% HP with an enemy within 8 (86%); HP drains over ~10 rounds; victims flee and are run down
  (ranged champions cannot move and shoot). 61% have an ally within 8 two rounds before death, only 37% within 4.
  Only 7% carry 20+ gems. Our engine playing the ladder dive draft (zdive) does not reproduce this pressure;
  `bots/zgank` (dive draft + Bruiser + chase weakened enemies within 6) does (v28 44/80, 92% untraded).
- **Maps decide a lot** (v28): 10 worst maps 58/339 (17%) vs 61% elsewhere. monolith 2/30, lost_world 3/35,
  lanes 4/38, starfish 3/23, collision 4/29, elkring 7/40, contest 6/33, great_wall 10/48, starvation 8/27,
  corners 8/27. Per-map results for v31 are in section 4.
- **Monoliths**: we take 4 monolith gems a game, opponents 41; win rate 31% when they take one vs 53% otherwise.
- **Gem-dead maps** (contest): 0-0 ties are decided on lifetime gold; we died 55-90 times vs 0-9 (kill gold 100).
- **Capture theft**: opponents collect 23 gems/game from our clears vs our 14 (elk_arena 105, corridors 98).
- **Team close-out**: in 32 of 599 v28 losses our tributed + carried gems already reached 1000 (median ~40 rounds early).
- **boss_battle**: the only altar opens when the boss monolith dies; opponents kill it first and tribute while we sit
  on 700-3900 carried gems.
- **00lanes**: enemies stack the bottom gem lane (3.4 bodies vs our 2.4); we keep ~0.6 bodies in the gold-only top
  lane. Not fuel, not bush ambushes: fight quality in the gem lane.
- **01starfish side B**: lone full-HP champions walk into the 14-camp centre group whose edge they see (`live_hp`
  sums only visible camps, so `required_helpers` is 0).
- **Fuel is not why games are lost**: games with >= 50 suspended turns won 63% vs 52%; halving fuel-outs lost slightly.

---

## 4. 2026-10-25 analysis: v31 on the ladder vs the top 5 (Theory of Constraints)

Data: v31's 185 ranked games (from 02:20 UTC 25 Oct), the last 50 ranked games of Intercontinental Fish, Mite,
willow best girl, Claudus Maximus and Trzy Kwaterki (250 games), 40 replays profiled for rounds 1-400.

| Per 1000 rounds | collected | tributed | conversion | gems lost | deaths | clears | dead time |
|---|---|---|---|---|---|---|---|
| v31 | 771 | 560 | 73% | 128 | 9.9 | 37.8 | 13.1% |
| Intercontinental Fish (66% WR) | 1014 | 810 | 80% | 141 | 11.7 | 43.1 | 13.8% |
| Mite (64%) | 1018 | 869 | 85% | 98 | 7.2 | 61.7 | 9.3% |
| willow best girl (46%) | 856 | 677 | 79% | 82 | 4.3 | 54.4 | 5.9% |
| Claudus Maximus (46%) | 931 | 659 | 71% | 177 | 10.2 | 45.4 | 14.1% |
| Trzy Kwaterki (52%) | 961 | 784 | 82% | 74 | 6.0 | 50.5 | 8.2% |

- **Constraint: early economy.** Gold by r300: v31 928, top 5 1,405-1,496, our own opponents 1,016 (r500: 1,660 vs
  2,565-2,994). Gems at r300 are about equal. Camps cleared by r400: 13.9 vs 18-25; each champion type clears ~35%
  fewer than the same champion on top teams (Vesper 3.1 vs 5.0, Vendetta 2.9 vs 4.8). First clear r26 vs r17-22.
- **Not deaths**: Fish spends as much time dead as we do and wins 66%.
- **Where our early time goes** (r1-400 share of champion time): standing near camps without engaging 12.3% vs
  6-7% (Tavi 18%, Willow 15%: squad waiting), camp fighting 17% vs 22-26%, capturing 5% vs 8-9%.
- Not the cause: gold-only camp share (same as top teams), bodies per capture (1.04, same).
- **Top-team habits**: first emblem Treasure on nearly every champion, then Jungle, then stacked Bruiser (Fish puts
  14-19 Bruiser Strength emblems on Vesper/Marcella; Heart/Prism stack Bruiser Focus). Wards 70-228 per game (we
  place none; 13-28% on the enemy half). Bags median 22-29 (ours 36). Altar locks ~8/game from r55-68 (ours 4 from
  r102; Trzy none). Teleport crystals 4-7/game on melee divers, mostly on wall maps (road_of_riches 17/game,
  pilgrimage 16, fracture 12.5). Drafts: Vesper always first; Vendetta/Heart of Ruin/Marcella core; willow best
  girl opens Prism, Trzy opens Marcella + Ryth. 46-66% of their kills on the enemy half; traded deaths 11-20%
  (ours 6%). Games end ~1,050 rounds (ours ~1,340).
- **Local A/B of the exploit steps** (v35 base, 320 paired games vs zgank/zmeta/zpoke/zdive0; v36 off == v35 on
  32/32 games):

| Switch | gold@300 | gold@500 | clears@400 | wins |
|---|---|---|---|---|
| LESS_WAIT (regroup 4, give up 12, +10 rounds per missing helper in scoring) | +37 (1.8σ) | +74 | 13 -> 15 (11σ) | 248 vs 243 |
| TREASURE_FIRST (Treasure then Jungle on every champion) | +29 (2.1σ) | +51 | 0 | 249 vs 243 |
| BRUISER_ITEMS (Bruiser instead of Power) | +3 | +3 | 0 | 244 vs 243 |
| all three (shipped as v36all) | **+75 (3.6σ)** | **+155** | +2 | **259 vs 243 (+48 -32)** |

  vs v35/zhor/zrush: 200 vs 180 (+36 -16). No faults; fuel-outs 10.8 vs 9.2 per game. Local baseline gold@300 is
  1,087 (ladder 928), so this closes ~15% of the gap to the top 5. Farming metrics are mostly self-limited, so they
  measure locally (unlike fight fixes).

---

### v36all first ladder read (25 games, 09:40-10:20 UTC 25 Oct; means, compared with v31's 190 games)

- 18-7 (72%) on maps where v31 won 56% (about 1.6 standard errors: promising, not proven).
- gold@300 1,100 -> 1,173 (local A/B predicted +75); clears@400 13.9 -> 17.8; first clear r26 -> r24; tributed per 1,000
  rounds 561 -> 798; games end at r1,090 (v31 1,338); gems lost on death 169 -> 70.
- The 7 losses are death spirals on our own half with nothing traded: deaths 26.7 vs 1.9 per loss (interlock 71-2,
  eight 44-1, elkring 31-1 and 12-0, quadrants 14-0). **Marcella is the top killer in 5 of 7**, usually with Ryth /
  Heart of Ruin / Vendetta; 3 losses to one team (Quantum Tributers: Vesper, Willow, Marcella, Ryth, Heart). 00elkring 0/3.
- So the economy constraint is relieved in most games; in losses the binding constraint is now fights against
  stun-immune melee invaders (section 5 item 2).

### Band opponents vs us on engine 2.0 (2026-10-26; 4 panel teams x 20 recent ranked games, our 30)

- Deaths per game: them 4.0-17.9 (the uncancelables 4.0), us 20.4. Gems lost per death: them 3.6-5.9, us 10.6.
  Median bag: them 19-28, us 34. We collect the most gems by r300 (218 vs 139-187) and lose them in deaths.
- Drafts split into melee-bruiser teams (Heart, Marcella, Ryth, Ren, Vendetta; Jungle first, then Power emblems) and
  ranged teams (Tavi, Vesper, Prism, Willow; Bruiser or Treasure first). Altar locks 0-10 a game; wards 94-522.
- 00elkring replays (engine-2 reader: champion stride 420, camps at 6916): we spend 22-38% of rounds 0-400 on the
  enemy half (identical groups on both halves, our bodies spread to distinct groups), die there 18-54% of the time,
  carry 13-20 gem bags; they stay home, tribute every 22-44 gem capture, and keep 110-154 camp gems / 100 rounds.

 (not yet built or not yet conclusive)

Ordered by current priority.
1. **More early economy**: smaller bags, earlier shopping, dropping Monster and melee openers were measured and rejected
   (section 6). **Candidate `VESPER_STR_STACK`** (bots/v38vs0 = v36all + Vesper buys only Bruiser Strength after her
   openers): set 1 (zgank/zmeta/zpoke/zdive0) gold@300 +17 (2.9σ), gold@500 +47 (2.8σ), 267 vs 259 (+22 -14); set 2
   (v36all/zhor/zrush/zstack) gold@300 -7, gold@500 +34 (2.2σ), 250 vs 243 (+24 -17). Combined +46 -31, not yet significant.
2. **Fight conversion** (next constraint). Adversary `bots/zmarc` (v36all engine + Quantum Tributers draft Vesper/Marcella/
   Willow/Ryth/Heart + chase + melee bruisers prefer camps on our half) reproduces the ladder losses: v36all 42/80, deaths
   per loss 29.6 vs 8.5, 94% untraded, 64% on our half, Marcella top killer, interlock and eight 0/2. Replays of 985 deaths:
   69% have no ally within 4, usually one melee enemy within 3, HP 82% -> 53% -> 29% over 10 rounds, 59% keep fleeing,
   enemies nearby lose >10% HP in only 24%. Candidate `DUEL_STAND` (bots/v39ds: one melee chaser within 2 that reaches us
   anyway and has <= 2x our HP -> shoot back): zmarc 43 vs 38 (+6 -1), field 276 vs 267 (+13 -4), but v38vs0/zhor/zrush/
   zstack 249 vs 253 (+5 -9); 720 games +24 -14, not significant. The pick-off problem is not solved: next ideas are
   pairing ranged champions while invaders are seen, and stuns timed on Heart/Ryth (Marcella is stun-immune).
   `PAIRING` (bots/v40, shipped in v40pr: after any of us sees an enemy melee champion on our half - broadcast in byte 7 -
   ranged champions value groups with no ally within 5 and no ally claim at 0.25 for 80 rounds): vs zmarc 51 vs 43, our
   deaths 18.9 -> 14.8 and theirs 13.1 -> 16.0; elsewhere small losses (zdive0 -4, zstack -3, zmeta -3).
   Earlier fight notes: stay and trade instead of fleeing; R2 part 2 (scripted-policy search over
   3-4 policies for <= 3v3 skirmishes, < 15k fuel) on top of the fitted model (`tools/fight_build.py`, `fight_fit.py`).
3. **Wards**: earlier local tests (ward on capture / at altar) were neutral, but every top team wards heavily. Untested
   as forward vision for fights or contested camps.
4. **Teleport crystals** on wall maps (crystal range 3, ignores terrain, 3-turn channel).
5. **Monoliths** vs an opponent that takes them (`bots/zmono2`): vulture-style finish of softened monoliths, monolith
   mode on monolith-only maps.
6. **Team close-out**: needs a shared-memory slot; byte 7 is now taken by PAIRING's invader broadcast, so pack it elsewhere.
7. **Static ownership** of groups/altars from both spawn fields (infrastructure for map modes and capture guards).
8. **Map modes from the draft turn** (1M fuel, 1,024 read-only bytes; `draft.cpp` writes a plan nobody reads):
   FARM_RACE / MONOLITH / HOLD_HALF / GOLD_TIEBREAK / ALTAR_IN_CAMP, chosen from map features, never map names.
9. Particle belief for unseen enemies (feeds danger maps and altar safety).
10. Resource control (sit on enemy-side spawn tiles, lock-and-guard on <= 2-altar maps): mechanics confirmed, STARVE
    alone only slowed games we already led; needs a lock-breaking / sitter-killing adversary to test.

---

### Top-10 teams, engine 2.0 (2,469 ranked games, 250 per team, 27 Oct 02:40-10:50 UTC)

Teams: Intercontinental Fish (2,433, 69% in this sample), Mite (61%), Trzy Kwaterki, German Empire Destroyer Destroyers,
NEETCoders, prism best girl, Claudus Maximus, hello, Ad Astra, Supaswag (2,196). Data and scripts: ~/.cache/kessoku_top.
- **Draft:** a melee-bruiser core in almost every game: Marcella 84%, Vesper 82%, Vendetta 80%, Heart of Ruin 79%,
  Ryth 42%; Tavi 20%, Prism 18%, Cassi & Issac 11% (Fish 82%), Willow 11%, Varg 9%. First pick Vesper 36%, Marcella 21%,
  Heart 20%, Prism 18%. 3-champion maps: Heart/Vendetta/Vesper (118), Heart/Marcella/Vesper (95). We field Tavi, Willow
  and Varg, which they almost never pick, and never Heart or Marcella.
- **Who earns:** two melee/Vesper carries. Top earner per game: Marcella 375 of 900, Vesper 253, Vendetta 171. Average
  gold per game: Marcella 2,101, Vesper 1,901, Vendetta 1,200, Heart 872. Our Vesper earns 3,114 but Willow 469, Tavi
  765: one carry and weak farmers.
- **Economy:** gold@300 1,023-1,465 (Fish 1,465 with gold@100 434 vs ~300 elsewhere: Cassi & Issac's extra body); first
  shard r48-70; 14-25 tributes a game at 30-53 gems (Fish 23.6 x 37, Mite 24.5 x 33); 42-59 clears, ~2/3 on their own
  half, clusters the largest share (17-33 a game); 77-231 wards; teleports 0-5.3 and altar locks 0-8.3 a game.
- **Items:** Bruiser stacking everywhere (by far the most shards), small Treasure/Jungle/Durability/Monster openers,
  Home on some; new families (Prospector, Capture, Hunter, Skirmish, Greed, Collectors) almost unused.
- **Map types:** fight maps 1,178 games, 20 tributes x 36, 126 wards; normal 906, 17 x 44; race 385, 26 x 33, fewer
  deaths (5.5). Their gold@300 on our worst maps is 1.5-4x ours: the_pack 1,715 vs our 382, gold_rush 1,235 vs 496,
  treasure_box 2,076 vs 726, lanes 1,629 vs 971.
- **Closing gaps:** behind by 150+ gold at r300 they still win 22% (ahead: 83%). The comebacks win fights (deaths 7.1 vs
  10.8, kills on the leader), keep collecting gems (217 vs 207 at r300 despite less gold; 579 vs 497 at r600), bank more
  often (25.9 vs 17.6 tributes), farm the enemy half more (16.8 vs 12.8 away clears) and take monoliths (0.33 vs 0.22).
  Failed comebacks die (13.4 vs 4.9) and stop farming away (10.0 vs 20.8). Across all games, wins are decided by deaths:
  5.6 vs 12.1 in wins, 12.2 vs 5.4 in losses.

### v81 on the ranked ladder (ladder v51, 150 games 30 Oct 04:41-09:48 UTC; rows: `tools/analysis/ladder/v44_rows.py v51`)

- **49% (73/150)**; by size 3 champions 12/26, 4 champions 22/41, 5 champions 39/83 (v65: 45%, 59%, 50%). Losses are blowouts:
  50 of 77 lost by 300+ gems, 17 close (< 150).
- **Fights decide losses**: deaths 21.2 vs 4.1 in losses (wins 10.4 vs 9.9), only **4% of our loss deaths are traded** (an enemy dies
  within 8 rounds and 10 tiles), 69% isolated (no other ally death within 8 rounds and 8 tiles), 10.5 a game on our own half.
  Deaths are spread over the whole game (r0-299 3.4, r300-599 4.4, r600-899 4.7, r900-1199 4.3), so it is not just a bad opening.
  First death at round 257 in losses vs 491 in wins.
- **Cassi & Issac are the weak link**: 5.3 pair deaths per loss (each kills both bodies), then Tavi 3.3, Willow 2.9, Vesper 2.8,
  Varg 1.4. In wins C&I still die 3.0 times.
- **Killed by the bruiser core**: Heart of Ruin 4.4, Vesper 4.4, Marcella 4.1, Vendetta 4.0 per loss (Ryth 1.7). Win rate is flat
  (46-49%) whichever of these the opponent drafts.
- **Bags handed over**: gems lost 200 vs 53 per loss (Vesper 63, Issac 49, Tavi 30, Cassi 28); tributes 17 vs 31.
- **Early economy predicts the result**: gold lead at r300 -> 75% wins (75 games), behind -> 23%. In losses gold@300 896 vs 1,125,
  gems@300 200 vs 169 (we collect as much but die more: d<300 3.4 vs 1.3).
- Capture theft: they took 19 gems a game from our clears, we took 28 from theirs.
- Worst maps: 00corners 0/3, 02famine 0/3, 00contest 0/3, 00elkring 0/2, 01gold_rush 0/2, 01broken_curve 0/2,
  01concentrated_wealth 0/2, adgato_gemcombat3 0/2. Worst repeat opponent: FBOT5 2/10.
- Same profile as v65 (deaths in losses 23.2 -> 21.2, loss clears 48 -> 59): the v80/v81 changes trimmed it, not fixed it.
  Areas to work on: isolated untraded pick-offs on our half (C&I and Tavi first), carriers losing bags, and early deaths that
  sink the r300 economy.

- **C&I pair deaths (v51 summaries vs 80 Fish C&I games):** at death Cassi and Issac are 11+ tiles apart in 47% of our loss
  deaths (6+ in 66%), 53% on our half. Fish's halves are split as often (11+ apart: 43% in wins, 26% in losses) and Fish loses
  5.0 pairs per loss vs our 5.3, but only 2.3 per win vs our 3.0. So "the halves farm apart" is not the root cause on its own;
  the next step was replay death context (which half is caught, HP, enemies, allies), run on v51 replays with deathctx2.js.

- **C&I death context (v51 replays, deathctx2.js; 103 games: 279 pair deaths in 53 losses, 108 in 42 wins; run on AWS):**
  - Caught half: Issac 52%, Cassi 48% (wins 60/40), so it is not a Cassi-only problem.
  - Caught half's HP at t-8/t-6/t-4/t-2: 0.74/0.67/0.54/0.32, a slow drain from healthy.
  - An enemy is within 6 already at t-8 in 73%.
  - Enemies within 6 at t-2 in losses: one 46%, two 26%, three or more 16% (wins: two or more 64%), so losses are mostly lost
    1-on-1 chases.
  - Activity at t-4: walking 63%, camp fight 20%.
  - Where: own half 47%, middle 41%.
  - Partner 11+ tiles away in 49% of cases.
  - Nearest other ally within 4 in 47% of cases, but a free healthy ally within 8 in only 16%.
  - Bag carried: 6.9 gems on average.
  - Mechanism: one bruiser runs down a lone, walking C&I half over about 8 rounds, and the linked death costs both bodies.
  - Candidate fixes: CI_REGROUP (flee toward the partner, the partner converges), CI_TURN (a half that cannot outrun one melee
    chaser turns and fights, stun first), CI_PARTNER_PAIRING (partner-only pairing while invaders are about).

### v65 on the ranked ladder (ladder v44, 412 games 27 Oct 09:50 - 28 Oct 01:45 UTC, v67 window excluded)

213-199 (52%). Losses are fights, not farming: deaths 23.2 vs 4.8 in losses (9.9 vs 10.6 in wins), gems collected by
r300 level (215 vs 219), gold@300 928 vs 1,104 (kill gold), gems lost 192 vs 62. Loss types: fight deficit 76,
economy + fight 96, economy only 10, close 17. 93% of loss deaths are to champions, 52% on our own half; first
death median r111. Counting a Cassi & Issac death once, 57% of loss deaths are isolated pick-offs (no ally death
within 12 rounds / 10 tiles); Cassi & Issac are 37% of those. Replays (23 losses, 512 deaths): 89% HP 12 rounds
before death, 65% 6 rounds before; 2 rounds before, 42% have no ally within 6. Killers: Vesper 21%, Marcella 20%,
Vendetta 16%, Heart 15%. Worst maps: adgato_gemcombat1-5 about 6/41 (300-500 gold behind at r300, 15-27 deaths),
elkring 1/10, gold_rush 1/6. 3-pick maps 45% (4-pick 59%, 5-pick 50%). Worst opponents: Electric Tributers 1/9,
Memory? 2/10, Alpha pekka 4/15, Gilded Gold Clusters 4/15.

Deep-dive (2026-10-28, 23 loss replays, 512 deaths, sampled every 2 rounds): at t-8/-6/-4/-2 the victim has 76/66/48/20%
HP with the nearest enemy 4/3/3/2 tiles away; over t-6..t-2: chased with the enemy closing 32%, fleeing and caught 26%,
in a camp fight 26%, on a capture tile 8%, trading 7%. Own-half deaths (52%): nearest ally at t-6 median 4 tiles (52%
within 4, 31% beyond 8), that ally mostly walking (59%), at 85% HP and with its own enemy within 6 in 56% of cases; the
victim faces 2+ enemies in 59%. Early time split r0-300 (same classifier on 60 top-10, 11 v65-win, 23 v65-loss replays):
camp fight 26.9 / 27.1 / 21.2%, walking 33 / 41 / 35%, at spawn 8.0 / 2.5 / 3.3%, capture 10.1 / 8.6 / 6.7%, waiting
near a camp 4.1 / 6.2 / 4.5%, dead 6.5 / 3.9 / 15.6%. "Within 2 tiles of a live camp" (Observations.md) is 24 / 17 / 13%,
but our ranged champions hit from 3 tiles, so that metric understates our camp time; the real gap is ~8 points more
walking and ~5 points less time at spawn. adgato maps are all gem clusters (0 gold): gold there is kill gold (100) and
Marcella's tribute gold (top-10 gold@300 386 with Marcella, 191 without); v65 194 vs opponents 631 because we die 6.6
times before r300 to their 2.0. elkring: 10 identical elk groups, our clear tempo matches the top 10 (8.8 vs 9.9 before
r200, first clear r12 vs r11), losses are fights (deaths 28.8 vs 5.1). gold_rush: top 10 farm the gold-only clusters
first (243 of 325 clears before r200), v65 farms the wolf groups (44 of 72).

### v57br on the ranked ladder (ladder v41, first 135 games 27 Oct 02:50-07:10 UTC)

73/135 (54%; v39 49% over 455, v37 45% over 95) against opponents averaging ~1,690; rating 1,626 -> 1,693 (rank 265 ->
204). Deaths 11.3 vs 10.1 (v39 13.5 vs 8.6), gold@300 940 vs 931 (v39 862 vs 938); ~170 wards and 1.6 teleports a game.
| Cut | v39 | v41 |
|---|---|---|
| vs Stellar | 34% (73) | 62% (24), deaths 8.0 vs 13.4 |
| vs Cassi & Issac | 42% (77) | 45% (22) |
| opponent wards >= 250 | 42% (164) | 49% (49) |
| monolith maps | 44% (147) | 49% (47) |
| opponent uses teleports | 41% (82) | 45% (22) |
Still behind: camps cleared 40 vs 50 and gems lost to deaths 119 vs 85. PEEL (v58pl) not uploaded: deaths are near parity.
Note: /tmp was wiped on 27 Oct (scratchpads and the sprt cache); rollback zips now live in ~/.cache/kessoku_rollback,
ladder tables in ~/.cache/kessoku_ladder.

### v54po on the ranked ladder (ladder v39, 435 games 26 Oct 11:40 - 27 Oct 02:00 UTC)

209/435 (48%); rating rose to ~1,717 in the first 50 games (56%) and fell to 1,626 (rank 265). By quarter: 52%, 49%,
49%, 43% while opponents got weaker (1,700 -> 1,645) and Cassi & Issac drafts doubled (12-16 -> 29 games per quarter).
- **Champions:** win rate vs Stellar 31% (69 games), Cassi & Issac 39% (71), Varg 41%, Ren 43%; 48-55% vs the rest.
- **Wards:** vs low-ward opponents (~18/game) 56%, mid (~157) 49%, high (~427) 41%; our deaths 11.9 -> 16.3.
- **Teleports:** opponents used crystals in 16% of games (tangle, the_line, corridors, great_wall, vault, treasure_box);
  our win rate there 38% vs 50%. We never use them.
- **Monolith maps** 42% vs 51% elsewhere. **Close-out:** 29 of 221 losses had our tribute >= 850.
- **Items:** opponents who beat us buy ~74 Bruiser + 40 Power shards a game, those we beat ~27 + 18; v39 buys only
  Power (132) after the Jungle opener. New families (Prospector 28 games, Greed 11, Capture 10, Skirmish 4) are rare and
  not behind our losses.

### v52pa on the ranked ladder (ladder v38, first 50 games, 2026-10-26)

25/50. Opponents 1,647-1,713 (mean 1,677; us 1,659): 21/45 vs higher-rated. 40 maps in 50 games, so per-map rates are
1-2 games each. 17 maps lost every time: 02fields, 02treasure_box, adgato_gemcombat4 (0/2 each), 01shortcut,
adgato_gemcombat1, 00expanse, 02arena, 00the_line, 01fracture, 00contest, 00anvil, 02stalactites, 00corners,
00elkring, 01big_world, 02gift_wrapping, 02famine.
- **How we lose there (20 games, half fight / half race):** the enemy clears 56 camps to our 32, tributes 38.5 times
  to our 15.6 (27 vs 33 gems per tribute) and loses 28 gems to deaths against our 149; gold@600 1,383 vs 2,664.
  Race losses: few deaths (7.7 vs 3.0) but clears 29 vs 56 and gold@600 1,952 vs 3,173 - they simply farm faster.
  Fight losses: deaths 32 vs 4, kills 3 vs 31.
- **Their openers in those games:** Power Focus/Strength, Jungle Strength/Focus, Durability Health and Home Health
  before r400; teams we beat buy Treasure/Bruiser Strength like us. Our openers: Treasure Strength 7.5, Jungle Health
  6.2, Treasure Health 4.2 per game. Enemy drafts in those losses: more Marcella (65% vs 48%) and Heart (55% vs 36%).
- **Map structure explains little** (v37+v38, 145 games, weighted correlation with map win rate all |r| <= 0.26):
  losing maps have more monster-free cluster gems (r -0.26 on v38), more monoliths, fewer elk gems (r +0.18), fewer
  walls (r +0.21) and fewer equidistant (contested) gems.

### The 30 new maps (2026-10-26)

`tools/data/geo.json` holds the zgeo geometry of all 70 maps (groups with gems/gold/respawn/strength/kinds, altars,
terrain); `tools/data/spawns.json` covers all 70. New maps carry half the camp gold of the old ones (1,142 vs 2,130;
adgato_gemcombat1-5 none), 40% of gems in monster-free clusters (old 6%), fewer altars (2.2 vs 3.9). In 80 engine-2
games (ranked + panel A) we collect as many gems early but earn far less gold (gold@300 few-cluster new maps 713 vs
1,031, >=80% clusters 240 vs 731) and die more (15-22 vs 5-10); win rate 58% old, 32% new few-cluster, 42% new
cluster-heavy. `ITEM_ADAPT` (bots/v49ia: skip Treasure / Jungle+Monster by map economy) neutral locally (78 vs 79).

### v47h25 on the ranked ladder (ladder v37, 95 games from the "deadlock worst game ever" round, 2026-10-26)

43/95 (45%). Gold@300 decides it: ahead 80% wins, behind 20%; behind almost always means more deaths before r300
(3.3 vs 1.4). First death: median r73 in losses, r113 in wins.
- **Two kinds of loss.** 34 of 51 are fight losses (deaths 27 vs 7, gold@300 565 vs 1,136, tribute 464 vs 1,007).
  17 are race losses with few deaths (6.5 vs 3.1): we lead gems at r300 (224 vs 184) but earn 941 gold in r300-600
  against their 1,534, collect 906 vs 1,111 gems, drop 112 vs 49 to deaths; they reach 1,000 first (tangle, rows,
  road_of_riches, rushbait_v2, cuts, expanse, big_world, the_pack).
- **Untraded deaths.** 95% of our deaths in losses have no enemy death within 10 rounds and 8 tiles (late in wins 18%).
  Of 239 deaths before r400 in losses, 74% had an enemy within 6 tiles 12 rounds earlier, 44% no ally within 6,
  48% faced >2.5x our HP 4 rounds before (HP_RATIO_GUARD's threshold). Victims spread over Vesper/Tavi/Varg/Willow;
  killers Vendetta, Heart of Ruin, Ryth, Marcella. Camps kill few (1.2/game).
- **Opponents.** vs Cassi & Issac 1/9, Ren 4/14, Varg 8/25, Heart 19/49 (no Heart 53%). 0/5 vs Rogo
  (Heart/Marcella/Vesper/Ryth/Vendetta) and noobers (Heart/Ren/Ryth/Vesper).
- **Maps.** adgato_gemcombat1 0/3, 02uncharted_lands 0/3, 00monolith 1/4, 00reverse_spiral 1/4, 00quarry, 00lanes,
  00elkring, 01gold_rush, 02tangle, 02the_pack 0/2. Maps with 1,000-2,000 camp gold 33%.
- **Wards: we place 0, opponents 167 a game** (153 in our losses, 184 in our wins: not a direct cause).
- Local stage logging (bots/v51dbg vs zmarc/zgank, 301 deaths): the turns before a death end in normal farming
  (`turn:done`, 134) or banking (50) with an enemy at range 1-2 and HP draining, i.e. not judged outmatched; retreat
  starts at 30% when it is too late. Judging the fight by the HP exchange instead (`EXCHANGE_GUARD`) did not help.

## 6. Measured and rejected (do not retry without new evidence)

Local numbers are wins out of 70 (35 maps x 2 sides) or 80 (40 maps) per opponent unless stated; "field" = sum over
the fixed opponent set; SPRT = `tools/sprt.py` paired early-stopping test.

| Idea | Result |
|---|---|
| Re-score every round | 20/70 mirror (commitment beats reactivity) |
| Re-score every 8 / 12 | 267 / 256 field vs 271 (kept 4) |
| Tour planner, beam depth 3 (`TOUR_PLAN`) | 11/70 vs v24, 39/70 vs proxy; + re-score 12: 22, 55 |
| Opening plan from the draft turn | not built (same look-ahead idea as the tour planner) |
| Vesper capture rule off (`CAPTURE_ASSIGN=false`) | 29/70 (Vesper's gold bonus is worth idle bags) |
| `CLUSTER_VALUE` 0.5 | 36/70, neutral |
| `GOLD_WEIGHT` 0.06 / 0.03 / 0 | mirror 33 / 26 / 23 of 70 (gold buys stats) |
| Bounded fight sim (`FIGHT_SIM_OUTMATCHED`) | deaths 359 -> 303 but 35/70; `FIGHT_SIM_TRIBUTE` never fires |
| `FUEL_GUARD`, fuel switches (OBS_SKIP_FAR, BANK_CACHE, MOVE_SCRATCH) | halve fuel-outs, win slightly less (24/23 vs 27 of 36) |
| BANK_BAG 30 / 36 / 64 / 70, PVP_BANK_BAG 20 / 45 | flat within noise |
| Arrival-aware opening (value x0.7/0.6 for contested groups) | +4 zmeta, -7 zhor: net zero |
| Close-out at 800 / 900 tributed | no change (rare locally) |
| Lock our altar before tributing | 61 / mirror 33 |
| Ward on captured group / at altar | mirror 30 / 36 (neutral to worse) |
| Durability after Monster + Jungle | zpoke 40 (worse) |
| Squad convergence x2 / x4 (`SQUAD_CLAIM_BONUS`) | worse (zpoke 48 / 38) |
| Draft: Vendetta 4th / drop Willow | worse vs zpoke |
| Heart of Ruin 4th pick; golems as hostile | 309 / 328 vs 327 |
| Idle-bag bank rule | ladder pattern wins 60%: not a loss driver |
| A2 contested-capture fold | 231 vs 235 |
| A5 gem-dead zero-feed (`ZERO_FEED`) | 225 vs 235; loses the contest games it targets |
| A3 last-tick lock | mechanism exact, opportunity 6 times in 70 games |
| A4 primed tribute | mechanism confirmed; bags are empty when it could fire |
| B2 camp trap (`CAMP_TRAP`) | fired 3 times in 350 games, neutral |
| B3 respawn denial (`STARVE`) | neutral; wins 35-65 rounds slower |
| `FOCUS_STICKY` 0.3 / 1.0 | 231 / 235, neutral |
| `WILLOW_YIELDS` | 231, slightly worse |
| Sharing intel via the free memory byte (death spot, help calls) | 39/70 vs 43/70; `HELP_CALLS` 16 vs 17 |
| Adversaries (altar dipper, bush ambusher, control) | the exploit hurts the attacker more than us |
| `DASH_THREAT`, `WARD_ALTAR`, `LOCK_FIX` | 225 / 224 / zlock2 59 vs 65 |
| Decision-logic review B xcast / D xmarg / E xpart | 226 / 220 / 223 vs 241 |
| `OUTMATCHED` 0.9 / 0.7, `ptrend` early retreat | 305 / 278 / 319 vs 327: fleeing earlier loses |
| `STAND_SHOOT` alone | field 311, mirror 40/80 (likely the v29 ladder drop) |
| C1 `CAMP_DANGER` (awake camps as danger) | field 364 vs 389, starfish deaths unchanged |
| C1b `ALTAR_CAMP_WAIT` | 29 vs 33 on altar-in-camp maps |
| C2 `TEAM_CLOSEOUT`, `CLOSEOUT_MARGIN` 150 | 48 vs 48 |
| C3 `BOSS_ALTAR_OPEN` (+ `BOSS_RUSH_BAG`) | 10 vs 10 (never fires locally); with rush 0 vs 10 |
| C4 `MONOLITH_FIGHTS` / `WHEN_DOMINANT` / vulture / `MONO_QUIET` | 33-36 vs 34; MONO_QUIET mirror 20/44 |
| C5 `SPAWN_REGROUP` | 6 vs 7 |
| C8 `set_priority` (fighters first / last) | 43 vs 47 / 48 vs 47 |
| R1 `ISO_PATH` / `ISO_TARGET` | 48 vs 47 / 38 vs 44 (reject) |
| R3 assignment (Hungarian / greedy) | fuel blow-up 9 vs 22; greedy 26 vs 34 |
| `FIT_FIGHT` thresholds 0.025 / 0.043 / 0.35 | reject (0.20 shipped in v31: fleeing more loses) |
| `CC_THREAT`; `CAST_FIRST` + `VARG_SPLASH` + multi-camp 0.75 | 27-35; together 41-48 on PvP maps |
| `CONVERGE_ACT_ONLY` | fixed the standoff but cost 113-122 elsewhere |
| `DEATH_AVOID_REPEAT` | 244-243 |
| `ZERO_GEM_DISCOUNT` (lanes) | 143-150 vs v35 (reject) |
| starfish `PARTIAL_HP` / `TARGET_RECHECK` / gated v42 | starfish deaths 284 -> 142 but pool 76 vs 92; v42 51 vs 66 |
| `BUSH_COVER` (bushes count as safe) | +2%, LLR +0.58: inconclusive; assumes opponents never probe bushes |
| Ranged step-back vs melee chaser | loses (no damage dealt while fleeing) |
| `SMALL_BAGS` bank at 25 (behind 35), on v36all | bags 39 -> 34, gold@300 -30 (-2.3σ), 253 vs 259 |
| `SMALL_BAGS` bank at 35 (behind 45) | neutral: 257 vs 259 |
| `EARLY_SHOP` (r<300, >= 150 gold, walk <= 20 or recall) | first buy 81 -> 76, first lock 102 -> 93, gold@300 -24 (-1.9σ); wins 266 vs 259 and 246 vs 243 on a second opponent set (+32 -22 total, not significant) |
| `EARLY_SHOP` without the recall | 259 vs 259, 245 vs 243: neutral |
| `SMALL_BAGS` + `EARLY_SHOP` | gold@300 -45, 250 vs 259 |
| `NO_MONSTER` (drop Monster from every build), on v36all | gold@300 -21 (-2.2σ), 253 vs 259 |
| `MELEE_OPENER` Vendetta instead of Willow | gold@300 -70 (-2.9σ), first lock r87; wins 267 vs 259 (+35 -27) |
| `MELEE_OPENER` Marcella instead of Willow | gold@300 -57 (-2.6σ); wins 269 vs 259; with Vesper Strength 263 vs 259 and 247 vs 243 |
| `VESPER_STR_STACK` with 40% Health | gold@300 +12 (2.5σ), 266 vs 259 (weaker than pure Strength) |
| `FLEE_TO_ALLY` (escape toward the nearest healthy ally instead of home), on v38vs0 | zmarc 43 vs 38 but field 254 vs 267 (+16 -29) |
| `RESCUE` (converge on a hurt ally hit by 1-2 enemies at side power >= 0.8) | fires rarely: 38 vs 38, 268 vs 267 |
| `DUEL_STAND` wide (HP ratio 3, chaser within 3) | 307 vs 305 over zmarc + field |
| `HR_CAMP_K` 1.5 / 2.0 (HP-ratio guard trips at a lower ratio while an awake camp is within 3), on v47h25 | 189 vs 191 and 361 vs 360 (1.5); 187 vs 191 and 360 vs 360 (2.0) over 700 games: neutral locally (local bots do not invade early like the meta teams) |
| `PAIRING` variants on v39ds (720 games on 9 bots each): mult 0.5 / 0.1, window 40 / 160, bruisers-only trigger | 563-570 vs 570: neutral |
| `STUN_CHASER` (stun a non-Marcella melee enemy within 2 of us or next to a hurt ally; stun before escaping), on v40pr | 794 vs 786 over 12 opponents (+41 -33); zmarc 52 vs 51, deaths unchanged: neutral |
| `STUN_RESERVE` (no stuns on camps while enemies were seen in the last 30 rounds) | 778 vs 786; zmarc 46 vs 51 (+5 -14): worse |
| `STUN_CHASER` + `STUN_RESERVE` | 763 vs 786 |
| `WARD_AHEAD` (re-place ward each turn on the tile nearest the enemy spawn; ~300-550 wards/game), on v40pr | 759 vs 786 (+83 -110) |
| `WARD_POST` (ward on the enemy-facing side of each new target, kept until the target changes) | 768 vs 786 (+88 -106) |
| `DOOMED_CAMP` (lone champion leaves awake camps it cannot outlast + 2/4/6 rounds of chase, skips the group 40), bots/v50dc on v47h25, AWS 1,680 games | +23 -86 at 384 games (all three escape values) |
| `DOOMED_CAMP` + only when no ally claims the group, skip 15 | 1,330 vs 1,358 (+87 -115): breaks squad gathering |
| `EXCHANGE_GUARD` (outmatched when over the last 4 turns we lost >= 15% HP share and enemies within 4 lost < half that; no DUEL_STAND then), bots/v51eg on v47h25, AWS 1,680 games | 1,324 vs 1,358 (+119 -153); 10%: 1,334; 20% over 6 turns: 1,353 (+141 -146). zmarc 84-93 vs 94, deaths unchanged (13.9 vs 14.1): leaving earlier does not save a ranged champion a melee bruiser already reaches |
| Prevention, bots/v52 on v47h25, AWS 1,680 games: `PAIR_ANYWHERE` (PAIRING fires for melee enemies anywhere, not only on our half) | 1,352 vs 1,358 (+111 -117), deaths 6.90 vs 7.05: neutral |
| ... + `PAIR_ALONE_MULT` 0.1 | 1,329 (+117 -146) |
| `ISO_STEP` (ranged, no ally within 3, enemy melee within 4 / 3: take a kill, then escape) | range 4: 863 vs 936 at 1,152 games (+61 -134); range 3: 1,329; with PAIR_ANYWHERE: 876 vs 936. Worst vs zgank/zstack: stepping away gives up camps and fights |
| Re-test under the per-candidate protocol (focused target set, then full-pool non-regression), bots/v53 on v47h25: all five combined | target (14 worst ladder maps x zmarc/zgank) 33 vs 35: fail |
| ... singly on their targets: `ITEM_ADAPT` 31 vs 36 (12 low-gold maps), `ISO_STEP` r3 33 vs 35, `DOOMED_CAMP` 21 vs 20 (full pool borderline worse), `EXCHANGE_GUARD` 20%/6 35 vs 35 | EXCHANGE_GUARD + PAIR_ANYWHERE = **v53c**: full pool 1,342 vs 1,358 (+137 -153, within noise) -> packaged as kessoku.zip for the ladder test |
| `POWER_OPENER` (Jungle emblem of our damage stat, then Power with 50 Health per 100 damage shards; no Treasure/Monster/Bruiser), bots/v54po on v53c | 17 always-lost v38 maps x zmeta/zgank 51 vs 53 (+5 -7), camps by r400 12.5 vs 12.5, gold@600 2,052 vs 2,089: items do not explain the enemy's clear speed locally. Full pool 1,342 vs 1,342 (+136 -136) -> **kessoku.zip = v54po** (PAIR_ANYWHERE + EXCHANGE_GUARD + POWER_OPENER) for the ladder |
| Farming speed (v38 replays r1-600: in losses we are dead 17% of champion-rounds vs 6%, farming 15% vs 20%; in wins farming 18% vs 22%. Local stage profile: 43% of turns walking to camps, 22% fighting camps, 19% walking to bank with a 22-gem bag, 5% waiting for a squad). `BANK_OFTEN` (bank at 30, altar detours up to 8 tiles with 15+), bots/v55bo on v54po | 17 losing maps x zmeta/zgank 47 vs 51 (+3 -7); tributes 23 vs 25 (threat banking already lowers the bag): fail |
| `ALTAR_PULL` (carrying a bag, add 0.5 x the group's distance to the nearest altar x bag/48 to its trip time), bots/v55ap on v54po | target 54 vs 51 (+5 -2), gold@300 941 vs 909, deaths 8.5 vs 9.8; full pool 1,317 vs 1,342 (+106 -131: inside the -2*sqrt bar of -31 but leaning worse, mostly vs zdive0/zhor/v47h25/zmarc) -> **kessoku.zip = v55ap** for the ladder; v54po zip kept |
| v56 switches on v54po (v39), focused one-setting tests on AWS: `WARD_SCOUT` (ward toward the enemy spawn near our target every 10 rounds, ~156 wards/game) 14 fight maps x zmarc/zgank 37 vs 35; `CI_FOCUS` (target Cassi/Issac, weaker half first) vs new adversary `bots/zci` (always drafts Cassi & Issac; beats v54po 78/140) 59 vs 62; `CAPTURE_FIRST` 49 vs 51; `PROSPECTOR_MAPS` (Prospector opener when >= 30% cluster gems) 15 cluster maps 40 vs 40; `TP_SHORTCUT` (keep a crystal on wall maps, jump when it saves >= 9 tiles, ~2.7/game) 46 wall maps 150 vs 145; `TEAM_CLOSEOUT` (bank when tribute + our + visible allies' bags reach 1,000) 51 vs 51, never fired; `VULTURE` 22 monolith maps x zmono2/zmeta 63 vs 65; `PO_BRUISER` (Jungle opener, then Bruiser instead of Power) 17 losing maps x 3 opponents 72 vs 72 | pass: WARD_SCOUT, PROSPECTOR_MAPS, TP_SHORTCUT, TEAM_CLOSEOUT, PO_BRUISER; fail: CI_FOCUS, CAPTURE_FIRST, VULTURE |
| **v57br** = v54po + WARD_SCOUT + PROSPECTOR_MAPS + TP_SHORTCUT + TEAM_CLOSEOUT + PO_BRUISER, full pool vs 11 adversaries + zci (1,680 games) | **1,383 vs 1,327 (+187 -131)**, beyond the noise band (+-36); zmarc 98 vs 83, zmono2 111 vs 98, zmeta 130 vs 120, zstack 112 vs 103, zci 65 vs 62; deaths down nearly everywhere; only zdive0 117 vs 123. Without PO_BRUISER (v57): 1,365 (+180 -142). -> **kessoku.zip = v57br** |
| v58 on v57br (live v41), from the v39 ladder (Stellar 31% / 69 games, Stellar killed 247 of ours; 95% untraded deaths). New adversary `bots/zstl` (always drafts Stellar). `CASTER_PRIORITY` (target enemies whose ready spell is a big share of our HP) vs zstl/zmeta full pool 197 vs 200 (zstl 65 vs 70); `AOE_SPREAD` (don't end the turn next to an ally when an enemy area spell is ready within 6) 194 vs 200 (zstl 66 vs 70); `PEEL` (healthy, not outmatched: attack the enemy hitting an ally within 8) 14 fight maps x zmarc/zgank/zci 51 vs 50 (zmarc 22 vs 19, deaths 12.3 vs 13.9) | Stellar switches fail on their own adversary. PEEL full pool 1,368 vs 1,383 (+67 -82): inside the noise band (-24) but leaning worse; bundled as kessoku_v58pl.zip (old scratchpad), not replacing kessoku.zip = v57br (live v41) |
| v59 on v57br, clear speed (v41 ladder losses: the enemy clears 27.7 clusters / 12.5 wolf groups a game to our 10.3 / 7.3 and 48 camps on its own half to our 23; we take more big elk/golem groups). Focused 27 maps (always-lost + cluster-heavy) x zmeta/zgank/zmarc: `NEAR_SWEEP` (groups within 4 tiles score x2) 122 vs 120, clears 52.2 vs 44.6, by r400 15.9 vs 13.3, wins ~40 rounds sooner; `CLUSTER_VALUE` 2.0 114 vs 120; `OWN_HALF` (groups nearer our spawn x1.3) 118 vs 120 but gems lost 80 vs 99, deaths 7.7 vs 9.0 | NEAR_SWEEP full pool 1,368 vs 1,383 (+138 -153, inside -34), clears 54.1 vs 46.1; zci +6, zstack -13, zmono2 -6, zgank -6 -> **kessoku.zip = v59ns**. OWN_HALF a near miss on wins, strong on gem losses: retry candidate |
| Bigger design changes on v59ns (v42), bots/v60: static ownership (group ours / theirs / contested by walk distance ratio 0.8). `MAP_MODES` (spawn walk <= 35 fight: ours x1.3, theirs x0.6; >= 70 race: neutral; else 1.15 / 0.85) 33 close-spawn maps x zmarc/zgank/zmeta 166 vs 160, deaths 6.4 vs 7.8; `RAID` (>= 2 enemies dead, read out of vision: their/contested groups x2) worst-map set 121 vs 130, deaths up; `TRACKING` (unseen enemies remembered 16 rounds, slack 6, dropped only when every wall-aware reachable tile is seen) 14 fight maps x zmarc/zgank/zci 51 vs 47 | pass: MAP_MODES, TRACKING; fail: RAID. **v61** = v59ns + MAP_MODES + TRACKING, full pool 1,398 vs 1,368 (+156 -126, just inside +34): zstack 109 vs 99, zgank 105 vs 98, zmarc 104 vs 99, zci 76 vs 71, zmeta 125 vs 129; deaths 5.0 vs 5.9 -> **kessoku.zip = v61** |
| v62 on v61 (live v43): `RAID` narrowed to >= 3 dead (`RAID3`) or contested groups only at x1.5 (`RAID_CONTESTED`), worst/always-lost maps x zmarc/zgank/zmeta: 127 vs 129 each (deaths 8.1 / 7.9 vs 7.4); `BELIEF` (unseen enemy spread evenly over the unseen tiles it could reach, wall-aware; danger = threat x share within striking distance; altar unsafe at >= 25% within range), 11 race + 14 fight maps: 96 vs 101 (gems lost 96 vs 114, but clears 49.8 vs 51.0, deaths 8.8 vs 8.4). 0 faults on the biggest maps | all three fail; v62 dev bots deleted. Identity v62-off vs v61 differed in 2 of 6 games (a bitboard added to Foe changes fuel timing) |
| `TR_FIGHT_ONLY` (TRACKING only on fight-mode maps, to recover v43's panel-B race tempo), bots/v62tf vs v61 on the 37 non-fight maps x zmarc/zgank/zmeta | 169 vs 174 (+12 -17): fail, TRACKING helps there locally, so the panel-B drop is not explained by it. On top of v62tf (for information): `OWN_HALF` 27 maps 119 vs 125 (fail again); `PEEL` 14 fight maps x zmarc/zgank/zci 51 vs 51 (level). Nothing packaged; v61 stays |
| v63 = v61 + `OWN_HALF` + `PEEL` | focused 34 maps x zmarc/zgank/zmeta 167 vs 159 (+32 -24); full pool stopped by SPRT at 1,536 games: 1,255 vs 1,290 (+100 -135, beyond the -31 band) - zci 58 vs 66, zmono2 95 vs 103, zdive0 103 vs 110, zstack 95 vs 101. Fail; v61 stays |
| Opponent gaps from v39+v41 ladder (99 Cassi & Issac games, 42% vs 52%: deaths even 12.6 / 10.8, but they clear 58 camps to our 39 and lead gold@300 1,026 vs 831 - one pick, two farming bodies; 5/18 on 3-champion maps. 194 monolith-map games, 45%: they clear 0.64 monoliths a game to our 0.02, 28% of our deaths within 5 tiles of a monolith). Both teams may draft the same champion. Focused vs v61: `CI_DRAFT` (first pick Cassi & Issac) vs zci full pool 89 vs 76, vs zmeta/zgank 17 maps 55 vs 53; `MONO_TEAM` (MONOLITH_WHEN_DOMINANT at 25% of the map's gems) 22 monolith maps 100 vs 113; `MONO_AVOID` (awake monolith not our target = danger within reach + 1) 113 vs 113 | **v65** = v61 + CI_DRAFT + MONO_AVOID, full pool **1,471 vs 1,398 (+184 -111)**, twice the noise band: zci 101 vs 76, zmarc 114 vs 104, zmono2 119 vs 110, zpoke 127 vs 118, zmeta 132 vs 125; clears 61.6 vs 55.4, wins 32 rounds sooner, deaths 7.5 vs 5.0 (Cassi & Issac count as two). MONO_TEAM fails -> **kessoku.zip = v65** |
| `META_DRAFT` (top-10 core: open Vesper, Heart of Ruin, Vendetta, Marcella; 5th pick by score = Tavi), bots/v68md (Cassi & Issac draft off) and v68mdci (on), vs v65 | focused 17 always-lost maps x zmarc/zgank/zmeta/zci: 93 vs 104 / 100 vs 104; full pool stopped by SPRT at 768 games: 600 vs 674 (+38 -112) / 592 vs 674 (+32 -114). Clearly worse: our play logic is built for the ranged comp (30% retreat wastes Heart's missing-health passive, no Marcella tribute carrying, kiting/pairing rules) |
| META_DRAFT + `HEART_LOWHP` (Heart fights down to 12% HP with an enemy within 6 when not outmatched) + `MARC_CAPTURE` (designated capturer by gain: Marcella 2 gold per tributed gem x group gems, Vesper 20% of group gold), bots/v69mel / v69melci vs v65 | roles now match the top teams (Marcella tributes 280 gems and earns 2,028 gold a game, Vesper 252 / 2,387, Vendetta 152 / 1,037, Heart 136 / 895), but focused 96 vs 104 / 95 vs 104 and full pool (SPRT stop at 768) 603 vs 674 / 580 vs 674: no better than the bare meta draft. Dropped; the ranged core + Cassi & Issac (v65) stays |
| Economy and fights on v65, from v41+v43 ladder (175 games) by map mode: fight maps 48% (gems lost/death 8.4 vs 6.2), normal 58% (16.1 vs 11.5), race 61% (clears 37 vs 62); ~10% of our champion deaths traded; v43 ranked 55% over 40, clears 48 vs 53. Focused vs v65: `THREAT_BANK8` (non-race maps: bags of 10+ bank with an enemy within 8, was 4) 118 vs 115, gems lost 141 vs 172; `RACE_SOLO` (no PAIRING on race maps) 69 vs 66 (+3 -0); `FIGHT_SIM_OUTMATCHED` (existing fight sim: outmatched when we die or they keep more HP) 64 vs 63, gems lost 160 vs 270, deaths 13.0 vs 15.5; 0 faults | **v67** = v65 + all three, full pool 1,464 vs 1,471 (+119 -126, level): deaths 6.7 vs 7.5, gems lost 63 vs 72; zgank +9, zstack +12, zci -9, zpoke -6, zrush -6 -> **kessoku.zip = v67** |
| Patch build orders on engine 2.0.0 (`ITEM_PLAN`, dev bots/v43; 420 games each vs v40pr on 70 maps x zgank/zmarc/zmeta): 1 Capture-Treasure-Jungle-Monster 299 vs 293 (+45 -39); 2 Treasure-Capture-Jungle-Monster 292; 3 Monster-Jungle (no Treasure) 293, gold@300 -31; 4 Monster-Treasure-Jungle 297; 5 + Tribute 4th 285 (+21 -29); 6 Capture-Treasure-Tribute-Jungle-Monster 290; 7 Capture-Monster-Jungle 288 | none beats Treasure-Jungle-Monster; Treasure still pays at 10%; Tribute hurts |
| `BIG_GROUP_FULL_HP` (count unseen camps at full HP only for groups with >= 10 camps, strength >= 300 and an altar inside; on the 70-map pool that is only starfish's centre group; dev bots/v45, candidate bots/v45bg) | starfish side B: camp deaths 17.4 -> 5.1/game, all deaths 30.9 -> 15.8, but wins 12/13 -> 9/12 (two games lost the farming race); side A unchanged; other maps flat (zgank 88 vs 86, zmeta 126 vs 125 over 140 each). Not clearly better than v40pr locally: not handed over |
| + `BIG_GROUP_SQUAD` (take that group as a team: up to bodies-1 helpers, pool 0.9, 3x squad clocks; bots/v45sq) | starfish vs 12 opponents: side B 11/12 (v40pr 12/13), deaths 21.0 vs 30.9, camp deaths 6.3 vs 17.4, collected 1174 vs 1144; side A 12/12; starfish total 23 vs 23. Other maps (gate never fires) differ only by fuel-timing noise: 13 vs 20 discordant over 420 games vs zgank/zmeta/zmarc. Locally even with v40pr; its target is the ladder, where v40pr went 0/4 on starfish against the panel |
| `MOVE_SCORER` (food-postmortem style 9-tile scoring in skirmishes: threat/HP, hit and kill bonus, ally support, home pull, numbers-scaled threat; dev bots/v44), focus set 8 pick-off maps x zmarc/zgank, 32 games vs v40pr (21) | v1 10 (+1 -12; zmarc 1/16, deaths 23 vs 9); + only-when-threatened and lethal-tile guards 15 (+5 -11); threat weight 20: 15 (+2 -8). A generic scorer loses to the tuned rule chain (FIT_FIGHT, CONVERGE, DUEL_STAND, retreat) |

---

| v70 review fixes on v65 (external bug review; dev bots/v70, all switches off == v65 verified), focused 144 games on 24 maps x zmarc/zgank/zmeta (locks: x zlock2/zcamp/zmarc; chase: 14 fight maps x zmarc/zgank/zci; draft: 12 three-pick maps), then full pool 1,680 | `FIX_CAPTURE_CALM` (no 50% heal floor next to an uncaptured group) focused +10 -10, full +73 -94; `FIX_CAST_FIRST` (ranged cast range-4 spells before stepping in) +15 -11, full +106 -125; `FIX_SPELL_FIRST` (damage/stun spell before attack reset) +5 -4, full +24 -35; `FIX_TAVI_HP` (no field Health shards) +8 -8, full +49 -78 (clearly worse); `FIX_DRAFT_CI` (scored third pick on 3-pick maps) +2 -11 (fail); `FIX_LOCK_THREAT` +1 -2; `FIX_LOCK_EARLY` (lock before the tribute starts, own locks no longer block our tributes) +1 -2; `FIX_CHASE_BURST` (chase counts one attack) +3 -5; `FIX_MOVE_REVEAL` +10 -10. None gains; all four full-pool runs net negative. Nothing packaged |

| v71 review part 3 on v65 (dev bots/v70 switches, off == v65 verified): focused (fight switches 14 fight maps x zmarc/zgank/zci 84; economy 24 maps x zmarc/zgank/zmeta 144; locks x zlock2/zcamp/zmarc), full pool 1,680 for the passes | Focused: `GOLD_EARLY` (gold weight 0.25 before r300 / gold-only groups) +19 -8, `EARLY_BANK` (bank at 20 before r150) +8 -5, `SMALL_BAG_SHOP` (shop trip with a bag < 20) +9 -8, `SPELL_KILL_FIRST` +3 -0, `OWN_LOCK_OK` +1 -0 (pass); `CALM_SAFE` +7 -10, `ISO_LEASH` (outmatched and no ally within 4: disengage at 6) +5 -7, `NEAR_ALLY_FIT` (FIT_FIGHT allies within 4) +3 -5, `CONVERGE_WIDE` +10 -13, `EARLY_TEMPO` (small groups x1.6 before r250) +7 -10 (fail). Full pool: GOLD_EARLY +102 -127, EARLY_BANK +51 -74 (clearly worse), SMALL_BAG_SHOP +46 -66, SPELL_KILL_FIRST +8 -9, OWN_LOCK_OK +4 -3; all five combined (v71all) +100 -143, SPRT reject. Focused wins do not carry to the full pool; v65 stays |

| New adversary `bots/zhunt` (v65 engine + top-10 draft Vesper/Marcella/Vendetta/Heart/Ryth/Tavi, HELP_CALLS and RAID on, `hunt()`: from r60 a healthy champion walks in on a visible enemy with no other enemy within 5 when our side is 1.2x stronger there) vs v65 on 20 maps: v65 29/40 (pool average 88%); in v65's losses deaths 18.5 vs 7.1 (ladder losses 23.2 vs 4.8). Switches from bots/v70 vs v65 on all 70 maps x zhunt (140 paired) | ISO_LEASH +11 -7, FIX_CHASE_BURST +9 -6, FIX_MOVE_REVEAL +10 -7, NEAR_ALLY_FIT +6 -7, SPELL_KILL_FIRST +0 -2, CONVERGE_WIDE +12 -18, CALM_SAFE +9 -20, FIX_CAPTURE_CALM +12 -21. Full pool: ISO_LEASH +57 -63, FIX_CHASE_BURST +35 -37, FIX_MOVE_REVEAL +67 -87; all three combined zhunt +16 -12, full +87 -114; ISO_LEASH + FIX_CHASE_BURST zhunt +15 -15, full +65 -80. No gain anywhere: v65 stays |

| Review part 4 on v65 (bots/v70 switches, off == v65 verified), focused vs zmarc/zgank/zhunt on target maps, then full pool + zhunt; breakdown over all cached paired games (bruiser = zstack/zgank/zmarc/zhunt, race = 00rows/00galaxy/00split) | `SELECTIVE_GOLD` (0.28 for gold-only groups before r400; 0.20 before r300 on non-race maps with >= 4.5 gold per gem) 51 maps +28 -42 (fail). `ESCAPE_SUPPORT` (shields/heals before escaping, walk-compatible stun on the chaser) 14 fight maps +8 -13 (fail). `CAMP_GANK_GUARD` (awake camps in burst_at / FIT_FIGHT, camp reach instead of 3, escape when an enemy is within 4 in a camp fight) +12 -11, full +105 -116, zhunt +14 -23; bruiser +62 -69, race +2 -7, adgato +16 -8. `MARCELLA_OPENER` (Marcella over Willow, captures gem-only groups) +15 -15, full SPRT reject +61 -108, zhunt +12 -25; bruiser +47 -67, race +2 -17. Nothing ships |

| Dead-code cleanup of v65 (2026-10-29, `bots/v71` = v65 minus code that cannot run; v65 untouched) | Removed: in `next_item()` everything after the opener (the opener returns on every path, so `TREASURE_FIRST`, `BRUISER_ITEMS`, `VESPER_STR_STACK`/`VS_HEALTH_PCT`, `HEALTH_PCT`, `RYTH_BUILD`, `NO_MONSTER`, `HOME_SLOT` never took effect since `PO_BRUISER` shipped: the live build is Prospector on cluster maps, then Jungle, then Bruiser at `PO_HEALTH_PCT` 50), the Power fallback, `CAPTURE_FIRST`, `ITEM_ADAPT` (+ `IA_*`, `ia_skip_*`), `POWER_OPENER`/`PO_BRUISER` switches (always on); in the draft `TEST_FORCE_*`, `MELEE_OPENER` (0 = Willow), `HOR_DRAFT_SCORE` (0 = default), `COUNTER_DRAFT` (+ the enemy-draft read) and the 8-byte draft-memory plan (never read). Removed comments' measurements: HEALTH_PCT 0/50/100/200/400 -> 43/54/54/51/50 of 70 vs the Stellar/Ren/Varg/Ryth bot (v23 era); POWER_OPENER from the v38 ladder (enemies cleared 56 camps to our 32 on maps we always lost, opening Jungle + Power); PO_BRUISER from the v39 ladder (winners stack ~74 Bruiser shards vs ~27); RYTH_BUILD 0/1/2 all mirror 9/18, 2 shipped; Home slot after Monster 7/18, after Jungle 6/18; COUNTER_DRAFT changed no picks (mirror 8/18); ITEM_ADAPT never shipped. Kept `has_monster`/`MONSTER_BONUS` (runs every turn; removing could shift fuel). AWS identity run: full pool 1,680 + zhunt 140, +0 -0, wins 1,471 / 110 both, all 1,820 per-game summaries (outcome, rounds, gems, every champion metric) identical. Uploaded as ladder v46 (2026-10-29 08:31 UTC): Panel A 11/20, Panel B 11/20, every one of the 40 panel games identical to v65 (result, deaths, gems lost, collected, gold@300), so platform games are deterministic for identical play. Identical play; not a strength change |

| Structural fight ideas on v71 (2026-10-29, dev bots/v72, one switch at a time, off == v71 verified per switch; focused 14 fight maps x zmarc/zgank/zhunt 84, full pool 1,680, zhunt 140, all on AWS) | A1 `KITE` (ranged champion with a visible melee enemy within 7 and our side_power < 1.5x theirs routes walks around tiles within 3 of it): focused +8 -9 (fail), full +78 -73, zhunt +13 -16. Deaths/game fall vs the melee bots (zhunt 11.0 -> 9.8, zstack 12.9 -> 11.2, zgank 12.3 -> 11.2) but wins do not follow; zdive0 +10 -15, zci +11 -13. Dropped |
| A2 `TRADE_CAUGHT` (same setup; in escape() a ranged champion that cannot step out of any chaser's next-turn reach, is not under a lethal burst, has a foe in range and survives a 3-round simulate_fight fires instead of walking) | focused +15 -11 (pass), full +99 -102 (pass, net -3 vs -28 bound), zhunt +14 -19. By opponent: zmarc +17 -10, zstack +16 -14, zgank +18 -18, zci +17 -26, zrush +1 -6; deaths/game up slightly (zgank 12.3 -> 13.3). Passes the local gates without a gain; kept on as the base for B and C. Shipped alone as v72 (ladder v47, 2026-10-30): Panel A 9/20 (v71 11/20; deaths 22.2 vs 18.6), Panel B 9/20 (v71 11/20; deaths 17.5 vs 14.8, gold@300 958 vs 982). Rejected on the held-out panel; roll back to v71 |
| B `BUDDY` (on the A2 base; base = v72t with A2 on; Cassi follows Issac, other bodies paired by body order; on fight maps or with invaders seen recently the follower takes its living leader's claimed farm group) | focused +7 -24 (fail), full pool SPRT stopped early at 768 games +43 -110 (reject), zhunt +18 -31. Negative against every opponent: zgank +7 -20, zmarc +7 -17, zdive0 +6 -15, zmono2 +3 -11, zpoke +1 -8. Likely cause: tying the follower to the leader's target costs its own farm targets, and the team still loses the fights. Dropped |
| C `BRUISER_PRESET` (on the A2 base, base = v72 with C off, which matched the A2 runs in all 940 games; draft Vesper, Marcella, Vendetta, Heart of Ruin in order, CI_DRAFT and RANGED_META skipped, score() fills a taken pick and the 5th; Heart of Ruin shops the Focus line; PAIRING's lone-group penalty for every champion while invaders are about) | focused +6 -22 (fail), full pool SPRT stopped early at 768 games +42 -132 (reject), zhunt +13 -37. Negative against every opponent: zmarc +7 -23, zpoke +2 -19, zci +7 -20, zgank +7 -17, zmono2 +3 -15, zstack +8 -14, zmeta +1 -10. Fourth failure of the top-10 bruiser draft (after 600 vs 674, 603 vs 674, MARCELLA_OPENER); the Heart of Ruin focus build and all-champion pairing did not rescue it. Dropped |
| SomeNewStrategies.txt S1 diagnostics (2026-10-30, 682 ladder loss deaths in v44_loss_deaths.json, t-8..t-2) | An enemy within 6 at t-6 or earlier in 82% (t-8 alone 55%). At t-4 only 13% have a free ally (within 8, HP >= 50%, no enemy within 6 of it); 36% have a near ally that is itself fighting or hurt; 26% have no ally within 8. 303 were warned at t-8 and walking at t-4, the gap closing in 245 (caught while fleeing). Enemies within 6 at t-4: Vesper 208, Marcella 200, Ryth 169, Heart 134, Vendetta 129, Tavi 99. A rescue responder can address at most ~10-15% of loss deaths; most are team fights already joined |
| S1 `RESCUE_CONTRACT` (dev bots/v74 = v71 + switch; a champion with a real enemy within 5 that is outmatched or below 60% HP writes 0x80 + its map sector into its own claim byte; one free healthy ally within a radius growing 8 + 3/round (max 16) takes the contract by writing 0xF0 + victim body, walks to the victim and fights; lets go on beacon clear, victim death or 12 rounds) | focused +11 -13 (fail, level needed), full +117 -124 (pass), zhunt +17 -19. Deaths/game down vs divers (zstack 12.9 -> 11.2, zhunt 10.9 -> 10.2, zgank 12.2 -> 11.5, zdive0 6.3 -> 5.8) and kills up (zhunt 11.2 -> 12.5, zci 14.2 -> 15.6), but wins level; zpoke deaths 6.9 -> 7.7. Dropped per protocol. Identity note: Bot members added even with the switch off changed all 26 games on 00dunes (the 60k first-turn fuel check after init sits at the edge there); file-scope statics instead of members fixed it (bit-identical on 00dunes) |
| S2 `TWO_CLOCK` (bots/v74 = v71 + switch, off == v71 in 1,314 games; in escape(): time to death = HP / per-round damage of real enemies in reach (+1, spell at 0.25), time to kill = fastest-falling enemy in our range under our strength + allies within 3, time to help = nearest ally at >= 50% HP minus 2; kill a round before death -> fight; help before death -> flee towards allies within 10 instead of home) | focused +9 -14 (fail), full pool SPRT stopped at 1,152 games +46 -95 (reject), zhunt +11 -21. Deaths/game up: zmarc 13.6 -> 16.5, zci 10.5 -> 12.2, zmono2 7.9 -> 9.6, zgank 12.0 -> 13.3. Standing to fight on a projected kill repeats STAND_SHOOT/DUEL_STAND/A2 (all rejected); fleeing to allies repeats FLEE_TO_ALLY. Dropped |
| S3 `COUNTER_DIVE` (bots/v74 = v71 + switch, off == v71 in all 1,820 games; fight_enemies() priority +4 for an enemy melee champion within 2 (+2 with dash ready) of a visible ally below 70% HP, so attacks, stuns and spells go to the diver after sure kills; pure CC skips stun-immune Marcella) | focused +12 -10 (pass), full +70 -85 (pass: net -15 vs -25 bound), zhunt +11 -22 (worse, deaths 11.0 -> 11.7). Deaths down vs zstack 12.9 -> 11.7, zgank 12.3 -> 11.7; kills slightly down vs zmarc 18.4 -> 17.6. Passes the local gates without a gain, zhunt negative (like A2 before its panel failure); kept as a panel candidate |
| S4a `DIR_GHOSTS` (bots/v75 = v71 + switch, off == v71 in all 1,820 games; a ghost moves forward up to 3 tiles along the enemy's last observed step, stopping at walls). S4b warning wards not built: WARD_SCOUT already wards the tile nearest the enemy's approach within 8 of our target, and ward vision is private to its placer | focused +6 -6 (pass), full +48 -58 (pass: net -10 vs -21 bound), zhunt +11 -14. Deaths level (zmarc 13.2 -> 12.6, zci 11.7 -> 12.4). Ghosts only act while carrying 10+ gems, so the effect is small; passes without a gain, panel candidate |
| S5a `GOLD_RACE_OPEN` (bots/v76 = v71 + switch, off == v71 in 1,820 games; maps with >= 40% of camp gold in monster-free gold-only groups (00breadcrumbs, 01elk_arena, 00quarry, 00ribs, 01hooks, 00contest, 00stampede, 01gold_rush, 00pilgrimage): those groups score x3 before r200) | focused 9 maps x zmarc/zgank/zmeta +4 -6 (fail), full +49 -70, zhunt +5 -10. On the 9 target maps (234 games) +16 -15, gold 10,841 -> 11,270, deaths 7.9 -> 7.3; the other maps (switch idle, timing only) +38 -65. Dropped |
| S5b `GEM_MAP_GUARD` (bots/v77 = v71 + switch, off == v71 in 1,820 games; maps with no camp gold (adgato_gemcombat1-5): OWN_HALF's x1.3 for groups nearer our spawn and PAIRING's lone-group penalty for every champion) | focused 5 adgato maps x zmarc/zgank/zhunt +10 -5 (pass), full +30 -32 (pass), zhunt +5 -5. On the adgato maps over all 13 opponents (130 games) +21 -12, deaths 9.3 -> 6.3 per game; other maps (switch idle, timing only) +14 -25. Deaths down vs zstack 12.9 -> 11.8, zgank 12.3 -> 11.5. First structural switch with a gain on its target maps. Live alone as ladder v49 (v71 + S5b, bots/v77g, from 2026-10-30T03:25 UTC): Panel A 11/20 (20/20 games same result as v71), Panel B 12/20 (v71 11/20; deaths 15.1 vs 14.8, gold@300 983 vs 982). The only flip is 01big_world (has camp gold, switch idle there: timing); the two Panel B adgato games (gemcombat1/3 vs Dota2 is better than LOL) still lost, deaths 25 -> 28 and 15 -> 18. Not rejected by the panels but not shown to help either; the ladder (100+ games, adgato subset) decides |
| v78 = v71 + S3 COUNTER_DIVE + S4a DIR_GHOSTS + S5b GEM_MAP_GUARD, all on (user's choice; vs v71 cache) | focused fight 14 maps x zmarc/zgank/zhunt +12 -5, adgato 5 maps x zmarc/zgank/zhunt +9 -9, full +87 -94 (pass: net -7 vs -27 bound), zhunt +15 -25. Bruisers improve: zstack +18 -11 (deaths 12.9 -> 10.8), zgank +18 -11 (12.3 -> 10.9); zci +13 -20, zmono2 +5 -11. On the adgato maps over 13 opponents +19 -19 (S5b alone +21 -12), deaths 9.3 -> 6.9. Live as ladder v48 (2026-10-30): Panel A 10/20 (v71 11/20; deaths 19.9 vs 18.6, gems lost/death 4.1 vs 8.5), Panel B 10/20 (v71 11/20; deaths 17.4 vs 14.8, gold@300 914 vs 982). Panel B flips: lost 01hooks (deaths 9 -> 59), 01concentrated_wealth, 02crossing; won 01big_world, 00crater. Panel B's two adgato games (gemcombat1/3 vs Dota2 is better than LOL) lost both times, so the panels barely see S5b. **Rejected on the held-out panel**; roll back to v71 |
| v79 fuel cleanup of v71 (2026-10-30, no switch: HELP_CALLS deleted with its constants, call_help/answer_help, sector helpers, seen_help/help_fresh/help_mine, so Mem::HELP belongs to PAIRING alone; the tour planner block, its constants and the per-rescore `cands` list + `all_fields` scan removed; choose_target no longer asks group_score for unused value/time; g_breaks/g_break_kind/g_handoffs count only in KSK_TRACE builds via KSK_COUNT). Baseline: v71 loses 55.4 champion-turns a game to fuel exhaustion (1,240 of 1,820 games; median 14, p90 147; mostly after r300; Cassi, Tavi, Willow, Vesper) | full +74 -92 (pass: net -18 vs -26 bound), zhunt +8 -18. Fuel-suspended turns 55.4 -> 43.6 a game (-21%; zstack 69.5 -> 42.2, zci 68.0 -> 50.4, zgank 52.2 -> 36.3). Passes without a win gain; parked in bots/v79 so the v49 (S5b) ladder test is not confounded; candidate base for the next version |
| v80 = v79 fuel cleanup + S5b GEM_MAP_GUARD (user request 2026-10-30; vs v77g = v71 + S5b, live as ladder v49) | full +86 -95 (pass: net -9 vs -27 bound), zhunt +10 -17, adgato 5 maps x zmarc/zgank/zhunt +3 -2. Against v71 on the adgato maps (130 games) +19 -11 (S5b's gain kept). Fuel-suspended turns 58.3 -> 44.3 a game. zci is negative for both cleanups (v79 +13 -26, v80 +17 -27). Live as ladder v50 from 2026-10-30T04:11 UTC: Panel A **14/20** (best ever; v71 11; flips: won 00eight vs the uncancelables and vs Crimson Pathfinders, 00lanes vs Martin Shkreli's Defense Team; deaths 17.8 vs 18.6, gems lost/death 5.5 vs 8.5), Panel B **10/20** (v71 11, v71 + S5b 12; won 01islands vs team, lost 02the_pack vs team and 00vault vs Sic Mundus Creatus Est (deaths 1 -> 16); adgato games lost as before). Total 24/40 (v71 22, v71 + S5b 23). By the rule Panel B decides (10 < 11), but the margin is one game; the ladder over 100+ games is final |
| v81 = v80 + S3 COUNTER_DIVE + S4a DIR_GHOSTS (user request 2026-10-30; vs v80, live as ladder v50; S3's constants re-anchored after RESCUE_RATIO because their old anchor HELP_CALLS was deleted) | focused fight 14 maps x zmarc/zgank/zhunt **+15 -4**, full +85 -97 (pass: net -12 vs -27 bound), zhunt **+17 -17** (level; on v71 the same pair was +15 -25 in v78). Deaths level overall (7.6 vs 7.6), zhunt 11.5 -> 10.7; fuel unchanged (44.2 vs 44.3). Live as ladder v51 from 2026-10-30T04:41 UTC: Panel A 13/20 (v80 14; won 00elkring vs Crimson Pathfinders, lost 00elkring and 00lanes vs Martin Shkreli's Defense Team), Panel B **11/20** (v80 10, v71 11; won 02the_pack vs team and 00vault vs Sic Mundus Creatus Est (deaths 16 -> 2), lost 01hooks vs Dota2 is better than LOL (deaths 9 -> 61)). Total 24/40 (v80 24, v71 22). Not rejected (Panel B above v80); kept live, the ladder over 100+ games decides |
| Phase 0 `bots/zfish` (2026-10-30; ladder-proxy adversary for the one-slot draft plan, phase_0_benchmark_and_proxy_plan.txt): zhunt + Intercontinental Fish's draft (Vesper, Heart of Ruin, Vendetta, Cassi & Issac, Marcella) + switches `ZF_PREP` (Heart dash landing in estimate_dps via ability damage_amount(), dash-strike on one camp with strength >= 60, ready shield in helpers_for's allowance; Marcella capturer tier 100000 for groups of 15+ gems, Vesper's gold tier raised to 200000), `ZF_PASSIVE` (Heart's missing-health bonus on basic attacks; PROBE: champion::strength() stays 30 at any HP, damage_amount() of the dash scales, 150 -> 162 at 84% HP), `ZF_ITEMS` (Heart Jungle Focus then Bruiser Health 200 per damage shard; Marcella and Vendetta Bruiser Health 100). Calibration on AWS, each variant vs zhunt paired, both playing v81 on 70 maps x 2 sides | v81 win rate: zhunt 74%; draft only (zfa) 73%; + PREP/PASSIVE (zfb) 73% (zfb vs zfa +15 -15: the Heart/Marcella prep changes nothing measurable); + ITEMS (zfc) **66%** (vs zfb +20 -11, vs zhunt +28 -18); + HUNT_EDGE 1.0 (zfd) 68% (vs zfc +15 -17). zfc kept and **frozen as bots/zfish, source hash e1e9a323c8e8 (cambc 4.0.0)**. Realism vs Fish's 247 ladder games: zfish gold@100 251 / gold@300 836 vs Fish 434 / 1,465; deaths 16.8 vs 11.0 (v81 12.9). Harder than zhunt but still far below Fish's economy: a fight proxy, not a farming one. Lesson for Phase 1: the item lines matter, the H1-H4/M1 estimate fixes do not (on our engine) |
| Phase 3B `RANGE_PRESSURE` (2026-10-30; bots/v82 = v81 + switch, off == v81 on the 6-map ab.py set vs zmarc and v65, SUMMARY lines identical; use_support_abilities() counts an awake camp as pressure within its own reach - elk/golem 4, monolith 5 - instead of 3, so Varg shields while tanking an elk or golem from 4; burst_at/FIT_FIGHT/escape unchanged), AWS, v82rp (on) vs v81 | G1 focused (38 five-champion maps with elk/golem x zmeta/zgank/zmarc, 228) **+8 -3** (pass); G2 bruiser suite (700) **+26 -22** (pass; zhunt+zfish +14 -11; deaths 11.74 vs 11.87 a game); G3 full pool (1,680) **+40 -38** (pass, bound -18); race+adgato 252 games +6 -6. Camp-caused deaths unchanged (1.68 vs 1.68 on five-champion maps), gold@300 1,233 vs 1,235. Every gate passes but the effect is at noise level: 147 of 784 three/four-champion games (no shield holder drafted) also differ, from fuel timing alone (the reach lookup runs for every visible camp each turn). Run note: pulling the 3.5 GB of per-game JSONs back from AWS stalled for ~1 hour; the analysis was run on the instance instead (pair.py) |
| Phase 2A/2B (2026-10-30; bots/v82 = v81 + RANGE_PRESSURE on, switches `S2A_VENDETTA` (4/5-champion maps: Vendetta in Willow's opener slot, 5th pick still Varg) and `S2B_THREE_VENDETTA` (3-champion maps: C&I, Vesper, Vendetta); off == base on the 6-map ab.py set vs zmarc and v65; drafts confirmed in single games; the untouched map sizes played identical games), AWS vs v82base | **2A rejected**: bruiser suite +66 -105 (deaths 14.5 vs 11.7, gold@300 1,071 vs 1,159), full pool SPRT reject at 1,152 games +62 -120; worse on 4- and 5-champion maps and against farming bots too (zrush +0 -7, zmono2 +4 -10, zci +13 -29). Per champion (4/5-champion maps, bruiser suite): Vendetta herself out-earns Willow (1,032 vs 546 gold, 2.66 vs 1.90 deaths), but EVERY ally dies more and earns less (Cassi & Issac 2.99 -> 3.63 deaths, Tavi 1.48 -> 1.96, Varg 1.55 -> 2.08, Vesper 1.09 -> 1.46; Issac gold 885 -> 667, Varg 1,305 -> 1,084). Willow heals **11,213 HP a game** (about eleven 1,000-HP lives): she is the team's sustain, not a weak farmer; her low gold misled the plan. **2B soft reject, kept OPEN**: 3-champion maps +23 -38 (net -15, bound -15.6), bruiser suite +15 -23, full pool +14 -25 (net -11, bound -12.5, passes); fails the level-or-better rule but is not clearly worse, deaths 11.0 vs 8.0 and gold@300 1,072 vs 1,132 on those maps. Willow is not drafted on 3-champion maps, so the healing explanation does not cover 2B; it needs its own per-champion diagnosis before a retry. 2A+2B together: bruiser +81 -128, full SPRT reject. The pre-registered knobs (Vendetta build, Vendetta pairing) cannot replace the lost healing, so they were not run. Next draft step must keep Willow (e.g. Vendetta in Varg's slot on 5-champion maps). Run note: slim AWS pull, 7,072 games in 79 MB, ~11 minutes end to end |
| Phase 2C slot 5 on 5-champion maps (2026-10-30; bots/v82 switches `SLOT5` 1 Vendetta / 2 Marcella / 3 Heart, `MARC_CAPTURE2`, `HOR_PREP` and `BRUISER_ITEMS2` ported from zfish; off == base on the 6-map ab.py set vs zmarc and v65; drafts confirmed in single games; Willow kept), AWS vs v82base | Vendetta (current build) bruiser +52 -62 (fail), full +67 -76 (pass); Vendetta + more Bruiser Health bruiser +48 -62 (fail), full +62 -82 (pass, bound -26); **Marcella + capturer tiers + item line bruiser +53 -46, full +74 -73 (both pass)**; **Heart + prep + item line bruiser +56 -56, full +80 -81 (both pass)**. Only the SPRT summary lines survived: the session restarted during the pull, the manual re-pull failed (stderr hidden by `| tail`) and the instance was terminated, so the DEV/HOLD split and per-champion lines are missing. Marcella and Heart need a re-run for per-game data before choosing. Vendetta has now failed in Willow's slot (2A), Tavi's slot on 3-champion maps (2B, open) and Varg's slot |
| Phase 2C re-run, Marcella vs Heart in slot 5 (2026-10-30; same bots, per-game data kept; DEV = odd, HOLD = even positions of sorted pool.txt) | **Marcella ACCEPTED** (v82 `SLOT5 = 2`, `MARC_CAPTURE2`, `BRUISER_ITEMS2` on): bruiser +53 -46, deaths 11.57 vs 11.74 a game; zhunt+zfish +25 -24; full pool +74 -73 (deaths 7.04 vs 7.28); race+adgato +18 -12; DEV bruiser +28 -22 / full +40 -33, HOLD bruiser +25 -24 / full +34 -40 (bound -17). gold@300 1,271 vs 1,233 (5-champion maps 1,342 vs 1,279). 3/4-champion games identical but one. Marcella herself: 1,726 gold and 1.15 deaths a game vs Varg's 1,305 and 1.55; allies unchanged (Willow 1.99 vs 1.90 deaths, Vesper 3,260 vs 3,234 gold). Heart: bruiser +56 -56, full +80 -81, but DEV bruiser +28 -29 (loses the DEV choice); Heart 1,065 gold, 1.63 deaths. Local effect is small (level-plus); the ladder decides. Candidate v82 = v81 + RANGE_PRESSURE + Marcella slot 5 |
| v82 on the panels (ladder v52, live 2026-10-30 09:48 UTC; v81 + RANGE_PRESSURE + Marcella slot 5) | Panel A **10/20** (v81 13/20): paired vs v81 +0 -3, all three flips on 5-champion maps (00elkring vs Crimson W->L despite gold@300 1,647 vs 1,414; 00lanes vs lETHal W->L; 00eight vs the uncancelables W->L); 02arena games identical; deaths 17.9 vs 18.9, gold@300 1,459 vs 1,412. Panel B (held out) **10/20** (v81 11/20): paired +1 -2; 5-champion maps +1 -1 (01big_world vs Dota2 L->W, 01fracture vs Alpha pekka W->L); the other flip (02the_pack, a 3-champion map with an unchanged draft) comes from RANGE_PRESSURE's fuel-timing noise. Both panels together 20/40 vs 24/40, 5-champion maps +1 -4. The panels lean against v82 by about the noise level (one panel's sd is ~2.2 wins); the ladder decides |
| Phase 2D Tavi -> Heart (2026-10-30; v82 switches `S2D_HEART5` / `S2D_HEART4`, Heart in Tavi's opener position, `HOR_PREP` + Heart Jungle Focus / Bruiser Health 200 line; vs v82base = v81 + 3B + Marcella slot 5) | 5-champion maps: bruiser +52 -79, full +72 -105; 4-champion maps: bruiser +33 -54, full +50 -79 (all fail). **Root-cause diagnosis** (bruiser suite, per game): Heart deals far less damage than the Tavi it replaces (camps 17,163 vs 23,321 on 5-champion maps, 16,425 vs 26,114 on 4; champions 5,588 vs 8,446) but takes 3x the camp damage (10,414 vs 3,233) and 2.3x the champion damage (6,866 vs 2,993), dying 2.02 vs 1.35 a game (camp deaths 0.48 vs 0.18). Every ally also dies more (Cassi & Issac 2.81 -> 3.08, Vesper 0.93 -> 1.13, Willow 1.87 -> 2.10): Tavi's damage and stun are gone. Mechanism: with the Focus + Health line Heart keeps 30 Strength, so its basic attacks barely hurt, while HOR_PREP's estimate (dash landing + passive) tells it that it can solo camps -> it tanks camps it clears slowly. **Pre-registered fix variants** (both sizes on, DEV/HOLD judged): h1 = HOR_PREP + Strength item line (`BI_HEART_FOCUS = false`); h2 = no HOR_PREP + Strength line; h3 = no HOR_PREP + Focus/Health line |
| Phase 2D Heart fix variants (2026-10-30, pre-registered; both map sizes on, vs v82base) | h1 HOR_PREP + Strength line: bruiser +68 -102, full SPRT reject at 1,536 (+78 -134); h2 plain Heart (no prep) + Strength line: bruiser +65 -78 (DEV +35 -30, HOLD +30 -48), full SPRT reject at 1,152 (+57 -109); h3 no prep + Focus/Health line: bruiser +77 -97, full SPRT reject at 1,152 (+56 -125). The fixes cut Heart's camp damage taken (10,414 -> 7,353-9,071 a game on 5-champion maps) but not the cause: Heart still deals far less than Tavi (camps 12.7-19.5K vs 23.3K, champions 5.6-6.2K vs 8.4K), takes 2.2-2.5x the champion damage (6.6-7.4K vs 3.0K) and dies about 2.0 vs 1.35 a game, and allies still die more (Cassi & Issac 2.9-3.1 vs 2.81, Willow 2.05-2.19 vs 1.87). Remaining cause: Heart's damage is a dash every 8 rounds plus a missing-health bonus, and our engine plays it like the ranged farmer it replaces (30% retreat, no dive, no peel with the dash-stun); losing Tavi's ranged damage and stun is not compensated. A real fix is behavioural (Heart fight logic), not items/estimates. 2D parked pending that |
| Phase 2D Heart fight logic, pre-registered 2026-10-30 (on h2 = Heart in Tavi's slot on 4/5-champion maps, plain Heart, Strength line; vs v82base). Basis: top-10 Hearts are tanks (champion damage taken 8,702 vs dealt 4,621, kills 1.3, assists 3.5, 1.7 deaths, avg HP 84%, within 4 of an ally 50% of the time, first clears monster-free clusters); our h2 Heart already out-earns them (997 vs 859 gold) but never protects anyone | Variants: **hg** `HEART_GUARD` (an enemy champion within 3 of an ally and within 4 of Heart: dash-stun it if the dash can land, else pre-cast the shield, then step next to it and hit it; skipped when the burst on us is lethal or Heart is below 40% HP); **he** `HEART_ESCORT` (PAIRING's lone-group penalty also for Heart while invaders are about); **hc** `HEART_CLUSTER` (monster-free cluster groups x2 for Heart); **hall** all three. Judged on the bruiser suite + full pool vs v82base, DEV/HOLD split, and paired against h2 to isolate the logic |
| Phase 2D Heart fight logic results (2026-10-30; variants pre-registered above, on h2) | vs v82base: **hg** GUARD bruiser +66 -88, full SPRT reject at 1,536 (+88 -132); **he** ESCORT +62 -96, reject (+83 -134); **hc** CLUSTER +65 -80, reject at 1,152 (+58 -110); **hall** +75 -104, reject (+65 -111). vs h2 (the logic alone): hg +48 -57 (DEV +18 -27), he +57 -78, hc +54 -56 (DEV +27 -21, HOLD +27 -35), hall +74 -90; none passes DEV/HOLD. PROBE (trace build, 3 games vs zmarc): HEART_GUARD fires 170 / 177 / 30 turns a game and acts every time, so it is wired; Heart just does not convert it (champion damage taken 6,664 vs 6,822, dealt 5,786 vs 5,932, own deaths 2.23 vs 2.01, allies unchanged). With hall Heart fights more (kills 2.55 vs 2.13, champion damage dealt 6,733) but team deaths do not fall. **Conclusion after 7 fix variants in two rounds (items/estimates, fight logic): drop 2D.** Team champion damage is about the same with Heart or Tavi (~36-37K a game on 5-champion maps); the loss is Heart's own deaths (2.0-2.2 vs Tavi's 1.35, each a kill and a 155-gem bag) plus slightly more C&I deaths. Melee bodies in place of our ranged ones keep failing (Vendetta x3, Heart x2, the four whole-draft swaps); Marcella worked because she replaced another melee body (Varg) |
| C&I survival, pre-registered 2026-10-30 (from the v51 replay diagnosis: losses = one bruiser runs down a lone walking C&I half over ~8 rounds; v82 code: below 50% HP `retreat_if_hurt` escapes and never fights, Cassi's walk-compatible stun is never cast while fleeing, Issac dashes only at a lethal burst, PAIRING skips Issac, the partner is invisible beyond 8 tiles). Key point: a partner joining costs no extra life (the halves die together) | **V1 `CI_FREE_HITS`**: Issac hits an adjacent chaser (+reset) before stepping away in the retreat path; Cassi kills if she can, else stuns the nearest non-Marcella chaser in range before walking; Issac dashes away below 70% HP with a melee chaser within 2 (not only at lethal). **V2 `CI_REGROUP`**: a half with an enemy within 6 that is outmatched or below 65% HP sets bit 7 of its claim byte; it flees toward the partner (visible position, else its claimed group, within 14 and nearer than home); a partner at >= 50% HP that sees the bit moves in and fights, ignoring converge()'s side-power and bag gates. **V3 `CI_PARTNER_PAIRING`**: while invaders are about, both halves (Issac too) apply PAIR_ALONE_MULT to groups not within 7 of the partner (visible or claimed). **V4** all three. Stand-and-trade left out (STAND_SHOOT, TRADE_CAUGHT, TWO_CLOCK, DUEL_STAND wide all failed). Gates: focused 14 fight maps x zmarc/zgank/zhunt/zfish/zci, G2, G3, DEV/HOLD; extra metric: C&I deaths per game |

## 7. Performance and fuel

- Average use is 28-47k of 100k per turn; 1-9% of turns exceed 80k; ladder ~10-14 suspended turns per game, 100+ on
  `00lanes`, 60-90 on `01big_world`. Costs: `observe` 13-17k every turn; spikes in `choose_target` (to 83k), `farm`,
  `move_to` (to 60k), `bank` (to 61k), `build_group_fields` (to 71k in one call).
- **Keep BFS** (`distance_field::compute/compute_to`, engine bitboard flood fill): unit-cost grid, A*/Dijkstra would
  be slower in wasm. Waste is redundant searches, not the algorithm.
- Exact optimisations available behind switches: `bank()` altar loop by index with cached squares/reachability
  (34k -> 14k on lanes), `observe` group-state distance skip, member scratch buffers in `move_to`, nearest-first field
  building. None raised strength; a fuel-out only delays a decision, while skipping work changes it.
- Safe rules: cache only static data; fill caches lazily on first use, never in `init()` (the first-turn
  `fuel_remaining() < 60000` branch turns extra init cost into a different game); keep `try/catch` around
  vision-dependent calls; prefer index lookups.
- **Equivalence test** for any refactor or new switch: every game where neither build hit a suspension must be
  identical (rounds, tributes, deaths, gold, per-champion metrics); `tools/fuel_profile/equiv.py` for ab.py runs,
  or compare the `tools/sprt.py` cache JSONs.
- Fuel profiling harness: `Submission/tools/fuel_profile/` (`prof.h` RAII scopes, `main_profile.cpp`, `parse_prof.py`).

---

## 8. Testing method (lessons)

- Compare a change against **the same code with the switch off**, not an older build; verify off == base first.
- **A mirror win is not evidence**: several variants gained 4-8 mirror wins and lost 10+ to other opponents.
- Use `Submission/tools/aws_runner.py` for anything bigger than a quick check: ~800 games in 45 s on a 192-vCPU spot
  instance, identical results to the Mac, instance terminated automatically.
- Accept on the field sum (zgank, zmeta, zpoke, zdive0, plus zhor/zrush/zstack/zmono2 as relevant), with no opponent
  down by more than ~4 wins; check targeted maps separately; use `tools/sprt.py` for verdicts.
- Local opponents are forks of our engine: they do not reproduce ladder pick-offs, monolith takes, lane stacking or
  spawn camping. Build an adversary that reproduces the ladder pattern before trusting a local fight result.
- Farming-rate metrics (gold@300, clears@400) are mostly self-limited and do measure locally.
- After an upload, compare versions on the ladder with `tools/ladder_compare.py NAME=START_UTC ...` (win rate on the
  same map mix, deaths, traded deaths, theft). Need the upload time; 100 games is about ±5 points.

Adversary bots: `zgank` (ladder-style dive), `zmeta` (Stellar/Ren/Varg/Ryth/Cassi-Issac), `zpoke` (ranged kiter),
`zhor` (Heart of Ruin), `zrush` (rushbait comp), `zdive0` (dive draft only), `zstack` (gem-lane stacker), `zmono2`
(takes monoliths), `zspawn` (spawn camper), `zlock2` (altar locks), `zcamp` (altar camper), `zgeo` (map geometry probe:
groups, altars, spawns; spawns for all 40 maps in `Submission/tools/data/spawns.json`).
