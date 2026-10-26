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
- cambc 4.0.0 has no Linux wheel (macOS only), so `tools/aws_runner.py` refuses to launch until one exists.
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
| Patch build orders on engine 2.0.0 (`ITEM_PLAN`, dev bots/v43; 420 games each vs v40pr on 70 maps x zgank/zmarc/zmeta): 1 Capture-Treasure-Jungle-Monster 299 vs 293 (+45 -39); 2 Treasure-Capture-Jungle-Monster 292; 3 Monster-Jungle (no Treasure) 293, gold@300 -31; 4 Monster-Treasure-Jungle 297; 5 + Tribute 4th 285 (+21 -29); 6 Capture-Treasure-Tribute-Jungle-Monster 290; 7 Capture-Monster-Jungle 288 | none beats Treasure-Jungle-Monster; Treasure still pays at 10%; Tribute hurts |
| `BIG_GROUP_FULL_HP` (count unseen camps at full HP only for groups with >= 10 camps, strength >= 300 and an altar inside; on the 70-map pool that is only starfish's centre group; dev bots/v45, candidate bots/v45bg) | starfish side B: camp deaths 17.4 -> 5.1/game, all deaths 30.9 -> 15.8, but wins 12/13 -> 9/12 (two games lost the farming race); side A unchanged; other maps flat (zgank 88 vs 86, zmeta 126 vs 125 over 140 each). Not clearly better than v40pr locally: not handed over |
| + `BIG_GROUP_SQUAD` (take that group as a team: up to bodies-1 helpers, pool 0.9, 3x squad clocks; bots/v45sq) | starfish vs 12 opponents: side B 11/12 (v40pr 12/13), deaths 21.0 vs 30.9, camp deaths 6.3 vs 17.4, collected 1174 vs 1144; side A 12/12; starfish total 23 vs 23. Other maps (gate never fires) differ only by fuel-timing noise: 13 vs 20 discordant over 420 games vs zgank/zmeta/zmarc. Locally even with v40pr; its target is the ladder, where v40pr went 0/4 on starfish against the panel |
| `MOVE_SCORER` (food-postmortem style 9-tile scoring in skirmishes: threat/HP, hit and kill bonus, ally support, home pull, numbers-scaled threat; dev bots/v44), focus set 8 pick-off maps x zmarc/zgank, 32 games vs v40pr (21) | v1 10 (+1 -12; zmarc 1/16, deaths 23 vs 9); + only-when-threatened and lethal-tile guards 15 (+5 -11); threat weight 20: 15 (+2 -8). A generic scorer loses to the tuned rule chain (FIT_FIGHT, CONVERGE, DUEL_STAND, retreat) |

---

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
