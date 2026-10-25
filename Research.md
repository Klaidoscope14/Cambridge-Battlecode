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

## 1. Where we stand (2026-10-25)

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

## 5. Open ideas (not yet built or not yet conclusive)

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
| `PAIRING` variants on v39ds (720 games on 9 bots each): mult 0.5 / 0.1, window 40 / 160, bruisers-only trigger | 563-570 vs 570: neutral |
| `STUN_CHASER` (stun a non-Marcella melee enemy within 2 of us or next to a hurt ally; stun before escaping), on v40pr | 794 vs 786 over 12 opponents (+41 -33); zmarc 52 vs 51, deaths unchanged: neutral |
| `STUN_RESERVE` (no stuns on camps while enemies were seen in the last 30 rounds) | 778 vs 786; zmarc 46 vs 51 (+5 -14): worse |
| `STUN_CHASER` + `STUN_RESERVE` | 763 vs 786 |

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
