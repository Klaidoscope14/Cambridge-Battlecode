# kessoku — CAMBC 2026 champions bot

A full implementation of the agreed 7-point architecture, in Python, against
the real `cambc` SDK. **Builds to WASM and plays full matches on all 9 pool
maps, both sides, with 0 crashes.** It is a *working, robust baseline* that
currently loses to the shipped `starter-python` on raw gem throughput — the
gap is a tuning problem for the self-play loop (the harness is in place), not a
correctness one.

## How to build / run / test

This directory is a bot package; it needs a CAMBC workspace to build.

```bash
pip install --upgrade cambc          # the CLI (v2.1.6)
cambc init --yes .                   # make THIS repo a workspace (adds sdk/, maps/)
# ... copy bots/kessoku here if not already under bots/ ...
cambc build kessoku
cambc run kessoku starter-python --map maps/collision.map26a --view
cambc run kessoku starter-python --map maps/<m>.map26a --statistics replays/s.json
```

Entry point is `src/main.py` (runs its own `while True` loop, dispatching draft
vs gameplay, yielding with `cambc.end_turn()`). One `Bot` instance per champion;
state persists across turns in that object.

## Architecture — the 7 points → modules

| # | Point | Module(s) |
|---|---|---|
| — | Entry / per-champion controller (Layer A→B→C each turn) | `main.py`, `brain.py` |
| 1 | Risk-aware **EV banking** + shopping | `economy.py` |
| 2 | **3-layer decisions** with commitment/hysteresis | `constraints.py` (A), `objectives.py` (B), `tactics.py` (C), `objective.py` |
| 3 | **Geometric** map reasoning (distances, altar safety, camp ranking, fingerprint) | `mapinfo.py`, `nav.py` |
| 4 | **Hypothesis-driven draft** scoring (priors × map × counter) | `draftbrain.py`, `champions.py` |
| 5/8 | **Belief model**: observed/inferred/unknown, confidence decay, danger field | `belief.py`, `world.py` |
| 6 | **Mostly-independent agents** + draft-memory plan + 8-byte live hints | `plan.py`, `comms.py` |
| 7 | **Instrumentation** (metrics to replay stdout) + central tunables/flags | `metrics.py`, `config.py` |

Everything that affects a decision is a tunable in `config.py` (feature flags
for ablation, objective weights, EV/risk params, draft weights). That is the
knob board for point 7.

## Current status (measured, vs starter-python, full matches)

Tributed gems (ours vs starter needs 1000); **W = we won**:

| map | ours | | map | ours |
|---|---|---|---|---|
| **interlock** | **1010 W** | | monolith | 682 |
| lanes | 864 (marginal W) | | collision | 484 |
| packs | 842 | | elkring | 360 (56 deaths) |
| expanse | 838 | | corners | 116 |
| | | | rows | 0–418 (fuel-marginal) |

**Caveat:** `lanes` and `rows` are **fuel-marginal** — the per-turn
`DistanceField` recompute sits near the fuel ceiling on big maps, so different
*builds* of identical source flip the outcome (lanes sometimes wins ~1020,
sometimes loses ~860; rows 0–418). interlock is the one robust win. Fixing the
per-turn fuel cost (incremental/cached BFS) would make results stable AND
better — the single highest-value next task.

- **Correctness:** builds to WASM; **0 crashes / 0 bot errors**; plays all 9
  maps, both sides. From the first version (lost every map, 66–198 gems) to
  **winning 2/9** and competitive on ~4 more.
- **Key fixes:** (a) `_DBG` NameError that crashed every bank attempt; (b)
  `carry_risk` passed a Champion where a Vec2 was expected → wasted every turn
  with enemies + carried gems; (c) **winnable-fight gate** (`combat.winnable_camp`)
  — never solo-suicide into a camp we can't beat before dying; it also produces
  emergent grouping on elk (champions wait until enough allies are present).
- **Open issues (next, in priority):**
  1. **rows is fuel-marginal** — on big maps the per-turn `DistanceField`
     recompute occasionally bumps the fuel ceiling and a turn stalls → tribute
     swings 0–418. Fix = cut per-turn fuel cost (cache/incremental BFS). *This
     is a complexity/DSA problem, not strategy.*
  2. **corners** (small wolf/elk rush map) — champions farm but the farm↔bank
     cycle is too slow; likely crowding (5 champs dogpiling). Needs a proper
     champion→camp **assignment** (see "Algorithms worth adding" below).
  3. **elkring** still trades a lot of deaths (56) for its 360 gems.
- **Tunable toggle:** `tactics._farm_goals` skips elk as a routing target
  (helps most maps + survival). Flipping it to `is_monolith` only gives more
  wins vs *this* starter but is weaker elsewhere — decide with real ladder A/B.
- Matches vs the starter are **deterministic per build** (its RNG is spawn-
  seeded), so single runs compare configs — EXCEPT fuel-marginal maps (rows).
  Still A/B vs *varied* opponents (`eval.py`) before trusting a change; the
  starter is one weak opponent and optimizing only for it overfits.

## Algorithms (CP/DSA): tried + worth adding

- **Assignment / bipartite matching — TRIED, reverted (measured worse).**
  Implemented a real deterministic greedy champion→camp matching (each
  champion runs the same matching over stable ally/camp handles, so they agree
  without comms). It *lost both map wins*: our bottlenecks are carry-death and
  travel, not dogpiling, so spreading champions sent overflow ones on long
  treks. A good lesson in testing the hypothesis — nearest-camp routing wins.
  (The optimal Hungarian/min-cost-flow would still assign, so wouldn't fix the
  underlying "spreading is bad here" issue.)
- **Fuel/complexity budgeting + incremental BFS/caching:** the rows stall is a
  per-turn big-O problem; compute static fields once, update incrementally.
- **Winnable-fight = greedy feasibility/simulation** (already added): turns-to-
  kill vs damage-taken arithmetic.
- **Prize-collecting TSP / orienteering + respawn-timer scheduling:** the deep
  structure of the farm→bank economy (max gems per time); greedy/DP heuristics.
- **0-1 BFS / weighted Dijkstra:** danger-aware routing over the belief field.

## Key findings from self-play (point 7 in action)

The harness already produced two real improvements and one trap:
1. **Camp-threat survival bug** (biggest): `belief.danger` only tracked enemy
   champions, so we fought camps to death and "recalled in place" (cancelled by
   camp hits). Fix: flee/disengage for camps too → deaths 23→6, tribute 198→396.
2. **Over-correction:** dying to a *camp* only costs carried gems + a full-HP
   respawn, and camps don't chase — so fleeing camps is *slower* than tanking.
   Fix: flee enemy champions / protect carried gems, but **face-tank camps when
   empty-handed** → expanse 140→556.
3. **Trap:** forcing aggressive banking (mimicking the starter) *reduced* score
   on some maps — a reminder to A/B with averaging, not single matches.

## Next steps (the tuning loop this is built for)

1. **Average, don't eyeball:** run each config N× per map, both sides, via
   `cambc run-batch` + `--statistics`; aggregate win rate, tributed gems,
   gems-lost-on-death, gems/100 rounds, camp-clear time, deaths, fuel.
2. **Close the throughput gap first** (it decides games): camp target selection
   (prefer killable camps; use focus bursts/emblems to clear faster), tighter
   farm↔bank cycle, less time in transit.
3. **Ablate** each subsystem (flags in `config.py`) to confirm it earns its keep.
4. **Tune draft weights** from outcomes; verify per-map strategy codes.

See `../../Maps_Analysis.md` for the exact pool geometry the draft/strategy keys
off, and `bot error` / `METRIC …` lines in the replay bundle's `team-*.stdout`
for per-champion diagnostics.
