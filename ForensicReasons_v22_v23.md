# Why it happened: code-level reasons for ForensicReport_ladder_v22_v23.md

Date: 2026-10-21. Companion to `ForensicReport_ladder_v22_v23.md` (what happened) and
`AlgorithmReview.md` (what to build). Bot: internal v24 unless stated.

Labels: **REPRODUCED** = seen locally with a per-turn trace; **MEASURED** = local A/B
(35 maps x both sides = 70 games, parity 35); **CODE** = follows from reading the source;
**OPEN** = still unexplained.

## 1. The `00rushbait_v2` stall (report A1): REPRODUCED, mechanism found

The report could not reproduce the stall against the field proxy (Stellar/Ren/Varg/Ryth).
With the exact opposing comp from that game (Ren, Stellar, Cassi & Issac, Varg; adversary
`bots/zrush`) and a per-turn probe, our side A shows the same pattern, with the same bag
sizes as the ladder game: Willow holds 29 gems from round 160 to 460 and Tavi holds 22 from
380 to 650, while their camp damage keeps rising.

Why (CODE, confirmed by the trace):

1. **Captures are reserved for Vesper.** `capturer()` gives every finished group worth
   >= `CAPTURE_GOLD_MIN` (60) gold to Vesper when she is within 6 tiles; everyone else skips
   the reward for 8 rounds (`farm()`, reward branch). This rule was tuned before patch 3.0,
   when Vesper was rarely drafted. Now she is drafted every game (`RANGED_META`) and almost
   every group pays 90-220 gold, so nearly all captures funnel into her (she had 131
   collected gems by round 400) while Willow and Tavi do the killing and their bags stop
   growing.
2. **Their small bags never reach a bank trigger.** 22 and 29 are under `PVP_BANK_BAG` (30)
   and `BANK_BAG` (48), and on this map the altars are 15-34 tiles away, so detour banking
   (<= 4 extra tiles) never fires either. The gems sit idle until the end or until a death.
3. The ladder's "almost no camp damage" is not reproduced: locally the bodies keep fighting
   for Vesper's captures. That difference is OPEN (likely the opponent kept them out of the
   groups in the real game).

Is it harmful? **MEASURED: no.** Turning the Vesper capture rule off (`CAPTURE_ASSIGN =
false`) is worse: 29/70 vs the otherwise identical build, 32/70 vs v24. Vesper's +33% gold
on captures is worth more than the idle bags cost. The report's own data agrees (the
pattern occurs in 45 of 180 games with a 60% win rate).

## 2. The opponent efficiency gap in the dip (report C1-C2): partly explained

Observed: opponents cleared fewer but richer groups (16.7 gems per clear vs our 14.0) and
turned camp damage into gems ~19% more efficiently, while our clears went up.

Reasons in our code:

1. **Target churn (MEASURED, the main lever).** `choose_target()` re-scored every 4 rounds
   and switches when another group scores 1.3x better. With patch 3.0's longer games and
   more groups, this churn costs travel: bodies abandon half-walked trips. Re-scoring every
   12 rounds is the best change found: 40/70 vs v24 and 62/70 vs the field proxy (v24: 53).
   The AlgorithmReview predicted this ("commitment beats reactivity").
2. **Cheap clusters (CODE, MEASURED neutral).** Patch 3.0 cut gem/gold cluster HP from 500
   to 120, so cluster groups (0-4 gems, 40-60 gold) score very high on value per time and
   inflate our clear count. Halving their value (`CLUSTER_VALUE = 0.5`) was neutral (36/70),
   so this is a symptom, not a lever.
3. **Fuel (MEASURED).** On big maps each re-score cost ~45K fuel (a full-map BFS from the
   champion), and turns ran out mid-decision. Cached per-group distance fields remove that;
   alone they lifted the field-proxy result from 53 to 59/70 with the same decisions.
4. OPEN: whether opponents changed their code or the balance patch (3.0.x) went live in that
   window. Nothing in our code changed then.

## 3. Timeouts on contest / elk_arena / stampede (report B3/C3): CODE

`MONOLITH_FIGHTS` and `MONOLITH_WHEN_DOMINANT` are off, so `group_score()` returns -1 for
every monolith. On `00contest` the monoliths are 100% of the gems, so we cannot tribute and
lose on gems at round 2000 whenever the opponent kills one. Earlier monolith variants lost
locally because our squad softened the monolith and the opponent finished it. Still OPEN;
needs a monolith plan that commits the whole team at once.

## 4. The `00lanes` contested box (report A2): CODE, partial

`outmatched` uses the Lanchester product (`side_power`), which ignores burst timing, stuns
and range. A bounded focus-fire simulation (`FIGHT_SIM_OUTMATCHED`) lowers our deaths vs
the field proxy (359 -> 303) but does not change wins (35/70 vs the otherwise identical
build), so it is built but off.

## 5. What did not work (do not retry without new evidence)

| Change | Result |
|---|---|
| Tour planner, beam depth 3 (`TOUR_PLAN`) | 11/70 vs v24, 39/70 vs proxy: look-ahead pulls bodies to distant "good route" groups |
| Tour planner + re-score 12 | 22/70, 55/70 |
| Vesper capture rule off | 29/70 |
| Cluster value x0.5 | 36/70 |
| Tribute-channel survival check (`FIGHT_SIM_TRIBUTE`) | identical games (never fires locally) |
| Opening plan from the draft turn (AlgorithmReview item 4) | not built: same look-ahead idea as the tour planner, which lost |

## 6. Shipped as internal v25

**Cached per-group distance fields only** (`GROUP_FIELDS`); decisions are unchanged, the
re-score just stops spending ~45K fuel on a full-map BFS. Re-scoring every 12 rounds looked
best against the mirror and the proxy but lost ground to the other adversaries, so
`RETARGET_EVERY` stays 4.

| Opponent (35 maps x 2) | v24 | v25 (fields) | fields + every 8 | fields + every 12 |
|---|---|---|---|---|
| v24 mirror | - | 37 | 37 | 40 |
| field proxy `zmeta` | 53 | **59** | 59 | 62 |
| ranged poker `zpoke` | 48 | **52** | 47 | 42 |
| Heart of Ruin bot `zhor` | 61 | **66** | 63 | 57 |
| rushbait comp `zrush` | 58 | 57 | 61 | 55 |
| **total of the five** | 255 | **271** | 267 | 256 |
| locksmith / camper / old bot / starter-cpp / starter-python | 66 / 70 / 70 / 70 / 69 | 65 / 70 / 70 / 70 / 69 | | |

Built behind switches and left off: fight simulation (`FIGHT_SIM_TRIBUTE`,
`FIGHT_SIM_OUTMATCHED`), tour planner (`TOUR_PLAN`), `CLUSTER_VALUE`.

Note: the "45-map pool" in HostileReview_v23.md was 35 maps plus 10 byte-identical duplicates
(hyphenated copies re-downloaded by `cambc init`); all numbers here use the 35 real maps.
