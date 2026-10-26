# How to submit (CAMBC 2026)

`Submission/` is a `cambc` workspace (cambc / SDK 3.0.5, engine 1.0.3 = the ladder's; `pip install --upgrade cambc`, then `cambc init --yes .` refreshes the SDK and maps). The bot is **`bots/kessoku`**, written in C++; its source is the current submission (v47h25 = v46gc + HP_RATIO_GUARD (K 2.5), also frozen as `bots/v47h25`; `bots/v47` is the same source with the guard off (= v46gc, ladder v36); `bots/v46gc` (ladder v36), `bots/v45sq` (ladder v35), `bots/v40pr` (ladder v34), `bots/v36all`, `bots/v35`, `bots/v31` and `bots/v28` are rollbacks). Adversary `bots/zmarc` reproduces the ladder's Marcella-invader losses.
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
Maps: `maps/00*.map26a` and `maps/01*.map26a` are the 40-map ladder pool (`cambc maps list`). `cambc maps pull` / `cambc init`
re-download some maps under hyphenated names: delete the copies identical to an underscore file and rename new ones to
underscores, or `tools/ab.py` plays those maps twice. `python3 tools/refresh_maps.py <team id>` extracts maps from our ranked
replays as a fallback. The unprefixed maps are older versions kept for reference.
Each team's stdout is inside the replay bundle (`.repl26a` is a zip: `team-a.stdout`, `team-b.stdout`).
Turn errors print as `bot error [stage]: ...`.

## A/B testing a change
Matches are deterministic, so compare against a frozen copy of the live version; a mirror at
parity wins half the games.
```bash
cambc build v29                                     # frozen copy of the live version
python3 tools/ab.py mytest kessoku v29              # all 40 pool maps, both sides, 8 in parallel
python3 tools/ab.py mytest_g kessoku zgank 00lanes  # specific maps
```
Faster verdicts: `python3 tools/sprt.py VARIANT BASE zgank,zdive0,zpoke --maps m1,m2,...` plays both bots on the
same shuffled games in batches of 16 and stops early on a sequential test over the games only one of them
won (cached per source hash, so the baseline is never replayed).
`tools/ab.py` wraps `cambc run-batch --release` and prints wins, tributed gems, deaths, gold
earned and bot faults per game. Results are cached per TAG under `$TMPDIR/kessoku_ab/`, so use
a new TAG (or delete the folder) after changing a bot. For variants, copy `bots/kessoku` to a
new folder, flip a `Cfg::` switch, and run `cambc build <variant>` once before parallel runs
(concurrent builds of the same bot break the first games).
Opponent set: `zgank` (ladder-style: dive draft, Bruiser items, chases weakened enemies; reproduces our ladder
deaths, v28 44/80), the field `zmeta zpoke zhor zrush zdive0` (sum over the five is the main local number),
`zlock2` (altar locks), `zcamp` (altar campers), `starter-cpp`, `starter-python`.
Debug traces: `cambc run-batch --log-limit 30000000 manifest.txt` keeps long stdout logs.

## Fast A/B on AWS (`tools/aws_runner.py`)
A 192-vCPU spot instance (c7i.48xlarge, ap-south-1, ~$1.6/h) plays ~800 games in 45 s, bit-identical to the Mac.
One command launches it, syncs `Submission/`, builds the bots, runs `tools/sprt.py`, copies the results into the local
sprt cache and terminates the instance (also on errors); a full small A/B takes ~1.5 minutes end to end. Needs `aws login`.
```bash
python3 tools/aws_runner.py ab v40pr v36all zmarc,zgank,zmeta --max 240 --alpha 1e-9 --beta 1e-9
python3 tools/aws_runner.py batch tests.txt          # one "VARIANT BASE OPPS [sprt args]" per line
python3 tools/aws_runner.py status                   # make sure nothing is left running
```
`--keep` leaves the instance up between runs (then `python3 tools/aws_runner.py down`); every instance powers itself off
after `MAX_MINUTES` (default 120). Analysis scripts that read the sprt cache see the results as if run locally.

## Ladder data
```bash
cambc matches list --team <team id> --kind ranked --limit 100 --json   # paginate with --cursor
cambc matches summary <match id> --json    # saves match-<id>.json into the CURRENT folder
```
In summaries, a death's killer often appears as `Unknown entity kind (1)` with the enemy
champion's roster id: those are champion kills. Full replay state (positions, health, gems at
any step) can be read in Node with the visualiser's engine wasm; see `../Research.md` (section 2).


Version comparison on the ladder (win rate vs the earlier version on the same map mix, deaths per
loss/win, traded deaths, deaths on our half, capture theft):
```bash
python3 tools/ladder_compare.py v28=2026-10-22T19:30 v29=2026-10-24T18:10 v30=<upload time UTC>
```

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
