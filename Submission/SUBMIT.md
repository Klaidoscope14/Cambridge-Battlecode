# How to submit (CAMBC 2026)

This folder is a **ready-to-use `cambc` workspace** containing our bot.

## What actually gets submitted
Only the **bot source**: `bots/kessoku/src/*.py` (+ `bots/kessoku/pyrightconfig.json`).
The SDK (`sdk/`), maps (`maps/`), build artifacts (`.cambc/`), and the
`starter-python` test opponent are **workspace scaffolding — NOT submitted**.
`README.md` and `eval.py` inside `bots/kessoku/` are dev aids; harmless if bundled.

## Prerequisites
```bash
python -m pip install --upgrade cambc     # the CLI (v2.1.6)
```
This folder was created with `cambc init`, so `sdk/` + `maps/` are already here.
If you move it or they go missing, re-run from inside this folder:
```bash
cambc init --yes .
```

## Build & test locally
```bash
cd Submission
cambc build kessoku
cambc run kessoku starter-python --map maps/lanes.map26a --view     # watch a match
cambc run kessoku starter-python --map maps/<m>.map26a --statistics replays/s.json
python bots/kessoku/eval.py --bot kessoku --opp starter-python --runs 3   # averaged A/B
```
Maps: collision, corners, elkring, expanse, interlock, lanes, monolith, packs, rows.

## Submit (two ways — pick one)

**A) Direct from the CLI**
```bash
cambc login            # opens browser to approve; 7-day session
cambc submit kessoku   # uploads source to your team
```

**B) ZIP upload**
```bash
cambc bundle kessoku -o submissions         # makes submissions/kessoku.zip (source only)
# then upload submissions/kessoku.zip on the platform's Submissions page
```
Follow compilation status on the Submissions page.

## Status / caveats before you submit
- Builds clean (WASM), 0 crashes, plays all 9 maps both sides.
- **Currently loses to the shipped `starter-python`** (it reaches 1,000 gems
  first), competitive on ~6/9 maps (lanes 796, interlock 614, packs 580, …).
- Known bugs to fix first: **corners/rows tribute 0** (carry→altar loop stalls),
  **elkring 56 deaths** (face-tanking elk backfires). See `bots/kessoku/README.md`.
- It is a legitimate, submittable bot — but you'd be submitting a work-in-progress
  baseline. Tune with `eval.py` (averaged, both sides) before a sprint lock.
