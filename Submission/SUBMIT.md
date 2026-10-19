# How to submit (CAMBC 2026)

`Submission/` is a `cambc` workspace (SDK 2.2.4). The bot is **`bots/kessoku`**, written in C++.

## Where the submission zip lives
The upload zip always goes to the **repository root**: `Cambridge_BattleCode/kessoku.zip`.
Nothing else in the repo is a submission artifact.

## Build, test, bundle
Run from inside `Submission/`:
```bash
cambc build kessoku --release                                   # same mode as the platform
cambc run kessoku starter-cpp --map maps/lanes.map26a --view    # watch a match
cambc run kessoku starter-python --map maps/rows.map26a         # other starter opponent
rm -f ../kessoku.zip && cambc bundle kessoku --output ../kessoku.zip   # bundle never overwrites
```
Maps: collision, corners, elkring, expanse, interlock, lanes, monolith, packs, rows.
Each team's stdout is inside the replay bundle (`.repl26a` is a zip: `team-a.stdout`, `team-b.stdout`).
Turn errors print as `bot error [stage]: ...`.

## Submit
Either upload `kessoku.zip` on the platform's Submissions page, or:
```bash
cambc login
cambc submit kessoku
```

## Bot layout (`bots/kessoku/src`)
- `main.cpp`: turn loop; logs any turn error with the decision stage.
- `draft.cpp`: scores champions for camp-farming throughput, tilted by map shape.
- `bot.cpp` / `bot.h`: per-champion logic (retreat, altar lock, PvP, banking, shopping, farming).
- `common.h`: every tunable (`Cfg::`) and the 8-byte shared-memory layout (`Mem::`).

Shared memory: bytes 0-5 hold each body's claimed camp group (id+1); bytes 6-7 broadcast
the latest capture (group id+1, round low byte) so allies skip respawning camps.
