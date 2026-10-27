# kessoku — CAMBC '26 Autumn bot (team HighCortisol)

A C++ bot for the Cambridge Battlecode 2026 champions game (`cambc` 4.0.0, engine 2.0.0): five-champion drafts,
camp farming for gems and gold, altar tributes, and fights between champions. First team to tribute 1,000 gems wins.

## Repository layout

| Path | What it is |
|---|---|
| `kessoku.zip` | The upload bundle for the platform (built from `Submission/bots/kessoku`). |
| `Submission/` | The `cambc` workspace: bots, maps, SDK (C++ only), test tools. |
| `Submission/bots/kessoku` | The current bot source (same as `bots/v57br`, ladder v41). |
| `Submission/bots/v47h25`, `v54po` | Rollback sources (ladder v37 and v39). |
| `Submission/bots/z*` | Local test opponents (e.g. `zmarc` Marcella invaders, `zgank` dive, `zci` Cassi & Issac, `zstl` Stellar, `zmono2` monoliths). |
| `Submission/tools/` | Test and analysis tools (see below). |
| `Submission/tools/data/` | Map pool, spawn tiles and map geometry (`geo.json`) for all 70 maps; the two real-opponent panels. |
| `Submission/SUBMIT.md` | How to build, test, bundle and submit. |
| `Research.md` | Everything measured so far: ladder analyses, panel results, every A/B test, kept and rejected. |
| `GameRules.md`, `BotAPICpp.md` | Game rules and the C++ bot API. |

## Bot in brief

Source is in `Submission/bots/kessoku/src/`: `bot.cpp` (turn logic), `bot.h`, `draft.cpp` (draft), `common.h`
(every tunable and on/off switch, `Cfg::...`, each with a comment saying what it does and how it tested).

Each turn: observe, threat check (fight model, HP-ratio guard, HP-exchange guard), retreat/escape, enemy fights and
peeling, altar locks, banking (threat-aware, detours), shopping, then camp farming with squad planning.
Notable current switches: Jungle opener then Bruiser stacking, Prospector on cluster-heavy maps, wards scouted toward
the enemy, teleport-crystal shortcuts on wall maps, team close-out banking, ranged champions paired with an ally once
invaders are seen.

## Quick start

From `Submission/` (needs `pip install cambc==4.0.0` and `cambc login`):

```bash
cambc build kessoku --release
cambc run kessoku starter-cpp --map maps/00lanes.map26a --view
rm -f ../kessoku.zip && cambc bundle kessoku --output ../kessoku.zip
```

After a `cambc` upgrade, delete every `bots/*/.cambc` build cache, or bots silently do nothing.

## Testing protocol

Every change is a `Cfg::` switch in a copy of the live bot:

1. **Identity check:** with the switch off, the copy plays exactly like the live bot.
2. **Focused test:** the change's target maps against 2–3 relevant local opponents, one setting; must be level or better.
3. **Full-pool check:** all 70 maps x both sides x 12 opponents (1,680 games); must not be clearly worse
   (net discordant games above −2·√discordant).
4. **Real opponents:** upload, then Panel A (diagnostic), Panel B (held out, accept/reject) and match groups against
   teams rated 100–150 above us; keep or roll back. The ranked ladder over 100+ games is the final judge.

Tools (from `Submission/`):

| Command | Purpose |
|---|---|
| `python3 tools/sprt.py VARIANT BASE OPP,OPP --maps m1,m2 --max N` | Paired A/B with early stopping; results cached per bot source. |
| `python3 tools/aws_runner.py batch FILE` | Runs `sprt.py` lines on a 192-vCPU AWS spot instance (~25x the Mac); needs `aws login`. |
| `python3 tools/ab.py TAG BOT OPP [maps]` | Quick local A/B, one line per game. |
| `python3 tools/panel.py run LABEL [--panel tools/data/panel_holdout.json]` | Real-opponent panels for the live submission. |

## Ladder history (recent)

| Ladder | Bot | Notes |
|---|---|---|
| v37 | v47h25 | 45% over 95 ranked games; panels A 4/20, B 11/20 |
| v38 | v52pa | + ranged pairing anywhere; panels 8/20, 6/20 |
| v39 | v54po | + HP-exchange guard, Jungle/Power opener; 48% over 427 games |
| v41 | v57br | + wards, Prospector, teleports, close-out, Bruiser stacking; full pool 1,383 vs 1,327 vs v39; panels 7/20, 9/20 |

Details for each version are in `Research.md`.
