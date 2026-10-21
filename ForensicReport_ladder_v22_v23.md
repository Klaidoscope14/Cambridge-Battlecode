# Forensic report: ladder v23 (internal v24) and ladder v22 (internal v23)

Date: 2026-10-21. Naming: the ladder numbers its submissions one below the internal numbers, so **ladder v22 = internal v23** (ranged opening Vesper/Tavi/Willow, live 19:30 UTC 20 Oct to about 04:15 UTC 21 Oct) and **ladder v23 = internal v24** (health shards, pair demoted, live from the 04:30 UTC batch).

## Evidence and its limits

Available: `cambc matches list/summary` for 254 ladder-v22 games and 5 ladder-v23 games (per-champion metric timelines, kill/death/gem/clear/fuel events with round and tile), our `stdout` and fuel logs from the two downloaded v23 loss bundles, current ladder ratings, geometry from a probe bot.

Not available, so everything below is labelled accordingly:
- No champion positions over time (only death/kill/ward/clear events carry a tile). No per-turn decisions. Nothing says why a champion stood still.
- No rating history. I use results against opponents' **current** ratings as a proxy.
- Version windows come from draft signatures and commit times, not upload timestamps. The `cambc` ladder shows no per-version rating.
- The bundle `stdout` of both v23 losses is empty (no exception text); `diagnostics.botFaults` is 0 in all 259 games.
- The balance patch (Stellar, Ren, Heart of Ruin nerfs; Vesper, Tavi, Vendetta HP) has no timestamp in the data. A hint only: Heart of Ruin disappears from opponent drafts after about 02:30 UTC (about 30% before, 0% in 3 consecutive half-hours after).

---

## Part A. Ladder v23 (internal v24): 5 games, 3-2

All five came from one batch against "Sutra Stack" (drafts without Cassi & Issac identify the build). Five games cannot support any global conclusion. Results: hooks win, expanse win, interlock win, rushbait_v2 loss (915 vs 1010 gems), lanes loss (915 vs 1015). Both losses were close; neither shows a bot fault.

### A1. `00rushbait_v2` loss (we: Vesper, Tavi, Willow, Varg vs Ren, Stellar, Cassi, Issac, Varg)

1. **Sequence (observed).** Collected gems were equal (1087 each). We submitted 915, they 1010; we ended with 80 gems carried and lost 92 to deaths. Submissions were level to r150, then **flat for ~450 rounds** (we 84 at r300, 84 at r600; opponent 102 -> 255). From r356 to r655 three bodies (Vesper 29 gems, Willow 29, Varg 22) held an unchanged bag and dealt almost no camp damage (264, 1235, 845 over about 280 rounds each); Tavi held 22 gems from r200 to r700 with 5.1k -> 6.8k damage. After the stall we out-paced them (r750 to r1500: +831 vs +628) but ran out of time. Opponent reached 1000 at r1558.
2. **Earliest material decision.** Not identifiable from this evidence. First costly event: r104, Vesper died carrying 51 gems 8 tiles from the north altar, killed by Ren. Larger cost: the stall.
3. **Root cause vs symptom.** The stall is the cause of the gap; the cause of the stall is **unknown**. Fuel (5 events) and exceptions (none) are ruled out. Altars sit at the map ends (14,0) and (15,79), about 38-40 tiles from the spawn, so a bank trip is an 80-round round trip.
4. **Type.** Cannot be classified: policy or code. Hypotheses, not observations: (a) squad wait ring in `farm()` (bodies hold outside a group until `allies_near >= need`, up to 40 turns, then skip 40 rounds and re-pick); (b) `farm()` with no target (`gid < 0`) parks near the soonest-respawning group; (c) bags of 22-29 sit under every bank threshold (48, or 30 when an enemy was seen in 40 rounds), so nothing sends them to an altar.
5. **Alternatives.** At r400 any of the three could have started a bank trip (+84 gems by about r480 for 80 rounds of travel) or farmed a different group.
6. **Systematic or random.** I could not reproduce the stall locally (v24 beats the field-comp proxy bot on this map both sides in ~1000 rounds). Across 180 ladder-v22 games, the same pattern (a body holding a >=15-gem bag for >=150 rounds with <1500 monster damage, no death) occurs in 45 games, win rate 60% with it vs 56% without. Not a systematic loss driver. **Do not change global policy on this single game.**
7. **Smallest narrow change (untested).** Count consecutive turns a body spends in the wait ring or with no target; at 30 turns with a bag >= 10, call `bank()`.
8. **Regression risks.** Wasted trips on big maps; squad targets lose helpers and stall differently; fights near the altar with a small bag.
   **Scenario:** 00rushbait_v2, 00starvation, 01big_world (altars far from spawn), both sides, vs frozen v24 and the field-comp bot. Measure: rounds with an unchanged bag >= 150, win rate, mean tribute size, deaths.

### A2. `00lanes` loss (we: Vesper, Tavi, Willow, Varg, Stellar vs Ren, Stellar, Cassi, Issac, Ryth, Heart of Ruin)

1. **Sequence (observed).** Submissions stayed level to r1200 (682 vs 667), then the opponent pulled ahead (1350: 767 vs 869; end 915 vs 1015). Vesper had 0 deaths and collected 487 gems (47% of ours). Tavi died 9 times, Willow 8, Stellar 5, Varg 3. 23 of our 26 deaths and 13 of their 18 fall in one 25 x 12 tile box (x34-58, y0-12): a mutual contested zone, traded 23:13. Champion damage taken 43.2k vs done 20.3k. First three deaths r111 (Varg), r126 (Tavi, camp), r155 (Stellar), all with empty bags.
2. **Earliest material decision.** Not identifiable; the early triple loss (about 180 body-rounds in 45 rounds) in that box is the first measurable tempo hit, but submissions were level afterwards, so it is not shown to be decisive.
3. **Root cause vs symptom.** Symptom: deaths and 215 fewer collected gems. Root: unfavourable repeated trades in the contested box (tactical), against a six-body comp with Stellar, Cassi, Heart of Ruin. We had five bodies to their six.
4. **Type.** Tactical (fight selection). Computational is not the cause: 145 fuel-exhausted events (about 1.9% of body-turns), concentrated early (45 in r0-300), none correlate with the deaths I can place.
5. **Alternatives.** Hold the 4-5 bodies out of the box once the first three died; unknown whether a safer lane existed on this 90 x 30 map.
6. **Systematic or random.** Repeated deaths at one place are mostly geometry: across 180 ladder-v22 games 68% of our deaths fall within 5 tiles of an earlier team death in the previous 400 rounds, but so do 63% of the opponent's. I therefore **withdraw the earlier "re-entry" suspicion** as a bug. Single game, no policy change.
7. **Smallest change.** None justified by one game.
8. **Note.** In all five v24 games we had one body fewer than the opponent (they took Cassi & Issac). Over the 180 v22 games body difference did not predict results (-1 bodies 65% wins), so I do not treat it as a cause.

---

## Part B. Ladder v22 (internal v23): the rise and the dip

### B1. What the data shows

- Results against opponents' current ratings (our rating 1647 now, was ~1466 on 19 Oct). Cumulative points above expectation climb from 16:00 UTC (internal v22 era) to a peak around 02:00 UTC, then fall. The absolute level is biased (current ratings), the shape is the point.
- Three phases of ladder v22: A 19:50-23:59 UTC 67-53 (56%); B 00:00-02:59 53-37 (59%); **C 03:00-04:20 15-29 (34%)**. Opponent mean rating is the same in B and C (1661), Elo-expected win rate 48% in both.
- Significance: P(<= 15 wins of 44 | p = .55) = 0.4%; with ~18 half-hour windows scanned post hoc, about 7%. Games arrive in 5-game series against one opponent, which inflates variance further; there were 9 series in C (results 2-3, 1-4, 2-3, 3-2, 3-2, 0-5, 2-3, 1-4, 1-3). **The dip is real as a pattern but statistically marginal.**

### B2. Candidate explanations, with evidence

| # | Hypothesis | Evidence | Verdict |
|---|---|---|---|
| 1 | Harder maps in phase C | Per-map win rates from A+B predict 55% for C's map mix; actual 34% (contest 0-3, elk_arena 0-3, collision 0-2 do appear, but fewer other maps) | Does not explain it |
| 2 | Stronger opponents | Same mean rating in B and C | Rejected |
| 3 | Opponents adapted to the balance patch | Heart of Ruin 21-28% -> 0%; Vendetta 0-7% -> 14-33%; Prism 0-13% -> 20-43%; Marcella, Willow appear. Their collection rose 799 -> 941 gems while ours stayed ~900, so the gem lead (+80 to +120 in A/B) vanished | **Supported, not proven** (timing of the patch unknown; opponent changes could be bots updating code) |
| 4 | Random streak | p about 7% after the scan, clustered series | Cannot be excluded |
| 5 | Our own regression | Same bot; bot faults 0; fuel events similar | No evidence |

### B3. Recurring failure categories (119 losses of 254 games)

Heuristic labels from per-game totals (collected gems, deaths, gems lost at death, end reason):

| Category | All | A | B | C |
|---|---|---|---|---|
| Out-farmed (opponent collected >= 150 more, comparable deaths) | 48 (40%) | 20 | 16 | 12 (41%) |
| Death spiral (>= 25 deaths and >= 1.6x the opponent's) | 36 (30%) | 19 | 12 | 5 (17%) |
| Timeout at 2000 rounds, lost on gems | 18 (15%) | 8 | 3 | 7 (24%) |
| Close race, no dominant cause | 10 (8%) | 4 | 3 | 3 |
| Carrier losses (>= 130 gems lost, +60 vs opponent) | 7 (6%) | 2 | 3 | 2 |

Reading: the dip is **not** more death spirals (17% of losses in C, down from 32-36%). It is more out-farming (41%, unchanged share but more losses) and more timeouts (7 in C vs 3 in all of B), mostly on contest (3 games), elk_arena (2) and stampede/starvation: maps where games run to round 2000. In those maps the result is decided by gems tributed in the closing stretch.

### B4. Per-loss forensic summary for the dip (29 losses in C)

- 12 out-farmed: 00split, packs, quadrants, ambush, the_farm, swirl, rushbait_v2, collision x2, elk_arena, shortcut, broken_curve. Gem gaps 217-968. Several with the opponent at 0-1 deaths and us at 13-19 (packs 17/0, collision 19/1, rushbait 7/1): the opponent out-fought us without losing bodies.
- 7 timeouts: contest x3 (deaths 114/28, 75/57, 32/44), elk_arena x3, stampede, starvation. All lost on tributed gems; contest gem gaps 600-1000 mean the opponent killed monoliths we never fight (`MONOLITH_FIGHTS = false`).
- 5 death spirals: eight, hooks, monolith, fragment, interlock (our deaths 28-38 vs 4-15).
- 3 close races (corners x2, rows) and 2 carrier-loss games (fracture, corridors).

For each category the earliest decision cannot be fixed from summaries. Root causes already supported earlier: health-less builds (measured, fixed in internal v24), and the contest/monolith blind spot (not fixed; fight-monoliths variant did not beat v23 locally).

### B5. What I cannot say

- Whether the rating dip corresponds to the balance patch, to opponents' updates, or to chance.
- Why individual bodies stood still or chose a group (no positions).
- The rating at any time; only results versus current opponent ratings.

---

## Proposed changes and measurement

| Change | Evidence level | Scenario | Measure |
|---|---|---|---|
| Keep internal v24 (health shards + pair demotion) | Measured locally (see HostileReview_v23.md) | Already in ladder v23 | Re-pull 100+ games: deaths/game (21 for v22 ladder), wipes/game, win rate vs maps in B3 |
| Narrow idle-bag bank (A1 item 7) | Hypothesis from one game | rushbait_v2, starvation, big_world, 70 games vs v24 frozen and the field-comp bot | idle-bag rounds, win rate, deaths |
| Contest/monolith plan | Open (variants failed locally) | 00contest, 01corridors, 00rows with a real monolith-killing opponent | tributed gems, timeout rate |
| Re-tune draft after balance patch (Vendetta 1000 HP, Stellar weaker) | Hypothesis | 35-map pool, new SDK | win rate vs proxy bots |

Wait for 100+ ladder-v23 games before reading anything into the 3-2 record.

---

## Part C. The ladder-v22 dip, using only the 254 games already played (44 in the dip window)

Windows: A 19:50-23:59 UTC (120 games), B 00:00-02:59 (90), C 03:00-04:20 (44; 15 wins, 29 losses). Map-mix and opponent rating are controlled where stated.

### C1. Where the games are decided

- The collected-gem lead at round 300 predicts the result: in A and B, a lead won 75-80% and a deficit won 33-34%. At round 600, 86-88% vs 16-21%.
- In C two things changed at once: fewer early leads (41% of games lead at r300 vs 54%) and worse conversion of a lead (win rate given a lead: 50% at r300 and 72% at r600 in C, vs 75-80% and 86-88% in A/B). Mean r300 lead: +28 in A/B, -4 in C.
- 9 of the 18 games in C where we led at r300 were lost. Their leads were small (7-88 gems at r300, peaks 77-300) and eroded while the opponent's camp damage rate exceeded ours (corridors 108k vs 54k, swirl 56k vs 41k, shortcut 28k vs 17k, corners 135k vs 104k, elk_arena 42k vs 30k) or while we lost bodies (swirl 24 deaths vs 6, starvation 25 vs 2).

### C2. What changed on the opponent side (map-adjusted, same maps in A+B)

| Measure (per game) | Ours, C vs A+B | Theirs, C vs A+B |
|---|---|---|
| Gems per 1k camp damage | -0.36 (se 0.24) | **+1.38 (se 0.39)** (+19%, about 3.5 sigma) |
| Collected gems | +15 (se 60) | **+148 (se 76)** |
| Gems per camp clear | 15.7 / 18.3 -> 14.0 | 11.9 / 15.3 -> **16.7** |
| Camp clears | 58 / 48 -> 67 | 67 / 52 -> 56 |

Reading: our throughput (camp damage, clears) did not fall. The opponents cleared **fewer but richer** groups and turned damage into gems more efficiently. Early collection (r0-300) rose from about 29 to about 40 gems per 100 rounds for them (ours 35-39). Against Stellar teams our win rate was 29% in C vs 56% before (n=34); against Ren teams 22% vs 59% (n=23). Nine different opponents show it, which points to something common (balance patch or a common opponent update) rather than one strong team. I cannot tell which from this data. Only two opponents appear both before and in C, so there is no clean same-opponent comparison.

### C3. Failure categories for the 29 losses in C (heuristic, from totals)

12 out-farmed with comparable deaths (41%), 7 timeouts lost on gems (24%: contest x3, elk_arena x3, stampede/starvation), 5 death spirals (17%), 3 close races (10%), 2 carrier-loss games (7%). The share of death spirals is lower than in A/B (32-36%).

### C4. Root cause vs symptom, type of failure, hypotheses

- Observed: opponents became more gem-efficient while we stayed put; early leads shrank and then eroded in the middle game.
- Type: strategic (target selection value) with a tactical component (lost bodies in 9 of the 29 losses). Not computational (fuel events similar), not a code defect (no faults).
- Hypotheses (unverified): (1) opponents re-tuned after the balance patch toward higher-value groups; (2) the patch changed which comps farm well (Vendetta, Marcella, Prism appeared; games vs those: our win rate 29-33% on n=6-7, too small to rely on).
- Whether the pattern is "systematic exploitation" or "randomness": the efficiency shift is statistically clear (3.5 sigma, post hoc), the win-rate dip alone is marginal (about 7% after scanning windows). I treat it as a real shift with an unknown cause.

### C5. Fix candidate tested on the spot

Target scoring values gold at `GOLD_WEIGHT = 0.12` per gold, so gold-rich groups pull champions off gem-rich ones. I tested lowering it on the current build (35 maps, both sides, parity 35):

| GOLD_WEIGHT | vs field-comp proxy | vs live build (mirror) |
|---|---|---|
| 0.12 (live) | 53/70 | - |
| 0.06 | 57/70 | **33/70** |
| 0.03 | 57/70 | **26/70** |
| 0.00 | 52/70 | **23/70** |

Rejected: it helps slightly against the proxy but loses heavily to the live build, because gold buys the health and strength shards. **No change recommended from this data.** Regression scenario if revisited: same sweep plus ladder pull of gems per clear; pass only if the mirror stays >= 35/70.

### C6. What would raise confidence without waiting for 100 new games

Nothing available now settles the cause. Cheap checks left: (1) check the ladder announcements for when the balance patch went live and compare phases around that time; (2) after the next few ladder-v23 series, compare opponents' gems per clear against the 16.7 figure here.
