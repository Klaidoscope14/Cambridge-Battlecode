# How to submit (CAMBC 2026)

`Submission/` is a `cambc` workspace (cambc / SDK 3.0.2; `pip install --upgrade cambc`, then `cambc init --yes .` refreshes the SDK and maps). The bot is **`bots/kessoku`**, written in C++.
Ladder team: **HighCortisol** (team id `58271d23-d86a-48de-987a-5d82c983d7db`).

## Where the submission zip lives
The upload zip always goes to the **repository root**: `Cambridge_BattleCode/kessoku.zip`.
Nothing else in the repo is a submission artifact.

## Build, test, bundle
Run from inside `Submission/`:
```bash
cambc build kessoku --release                                     # same mode as the platform
cambc run kessoku starter-cpp --map maps/00lanes.map26a --view    # watch a match
rm -f ../kessoku.zip && cambc bundle kessoku --output ../kessoku.zip   # bundle never overwrites
```
Maps: `maps/00*.map26a` and `maps/01*.map26a` are the 35-map ladder pool (`cambc maps list`); `cambc init` downloads them (rename hyphens to underscores). Older copies were extracted from our
ranked replays (`python3 tools/refresh_maps.py <team id>`; `cambc maps pull` fails). The
unprefixed maps are older versions kept for reference.
Each team's stdout is inside the replay bundle (`.repl26a` is a zip: `team-a.stdout`, `team-b.stdout`).
Turn errors print as `bot error [stage]: ...`.

## A/B testing a change
Matches are deterministic, so compare against a frozen copy of the live version; a mirror at
parity wins half the games.
```bash
mkdir -p bots/kbase && unzip -o -q ../kessoku.zip -d bots/kbase && cambc build kbase
python3 tools/ab.py mytest kessoku kbase            # all 35 pool maps, both sides, 8 in parallel
python3 tools/ab.py mytest_op kessoku oldpy 01hooks # specific maps; oldpy = old Python ganker bot
rm -rf bots/kbase                                    # remove the frozen copy afterwards
```
`tools/ab.py` wraps `cambc run-batch --release` and prints wins, tributed gems, deaths, gold
earned and bot faults per game. Results are cached per TAG under `$TMPDIR/kessoku_ab/`, so use
a new TAG (or delete the folder) after changing a bot. For variants, copy `bots/kessoku` to a
new folder, flip a `Cfg::` switch, and run `cambc build <variant>` once before parallel runs
(concurrent builds of the same bot break the first games).
Debug traces: `cambc run-batch --log-limit 30000000 manifest.txt` keeps long stdout logs.

## Ladder data
```bash
cambc matches list --team <team id> --kind ranked --limit 100 --json   # paginate with --cursor
cambc matches summary <match id> --json    # saves match-<id>.json into the CURRENT folder
```
In summaries, a death's killer often appears as `Unknown entity kind (1)` with the enemy
champion's roster id: those are champion kills.

## Submit
Upload `kessoku.zip` on the platform's Submissions page (or `cambc login` then `cambc submit kessoku`).

## Bot layout (`bots/kessoku/src`)
- `main.cpp`: turn loop; logs any turn error with the decision stage.
- `draft.cpp`: scores champions for camp-farming throughput, tilted by map shape.
- `bot.cpp` / `bot.h`: per-champion logic (retreat, altar lock, PvP, banking, shopping, farming).
  The phases communicate through `Bot` member fields set earlier in the turn (`observe` →
  `assess_threat` → retreat/escape → bank → farm), so phase order matters.
- `common.h`: every tunable and on/off switch (`Cfg::`), each with its measured A/B result,
  and the 8-byte shared-memory layout (`Mem::`).

Shared memory: bytes 0-5 hold each body's claimed camp group (id+1); byte 6 broadcasts the
latest capture (group id+1, top bit flips per capture) so allies skip respawning camps;
byte 7 is reserved for help calls (switched off).
