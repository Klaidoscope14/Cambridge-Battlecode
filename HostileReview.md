# Hostile review of `bots/kessoku` (v18)

Date: 2026-10-20. Scope: all of `bot.cpp`, `bot.h`, `common.h`, `draft.cpp`, plus `GameRules.md` and `BotAPICpp.md`.

## Method and labels

- I read the full source and traced decisions against the rules.
- I pulled summaries for the last 90 ranked ladder games (46 wins, 44 losses). I could not confirm which bot version played them.
- I built adversary bots and ran them with `Submission/tools/ab.py` (deterministic `cambc run-batch --release`, both sides of each map).

Labels:

- **MEASURED**: reproduced locally against an adversary.
- **LADDER**: computed from the 90 downloaded ranked summaries.
- **CODE**: defect found by reading the code, not run.
- **HYPOTHESIS**: strategic claim, untested.

Caveats:

- A mirror result of 26/42 is about +1.5 sigma over parity (21). It is suggestive, not proof.
- F1 and F2 were measured against simple adversaries. A competent opponent may do better or worse.
- The patch bundles several changes. I did not isolate each one, except that lock clearing plus the reachable-altar fix (F2 + F3) was run alone.

## Artifacts

All paths are relative to the repo root.

| Path | What it is |
|---|---|
| `kessoku_review_fixes.diff` | Patch for F1, F2, F3 (not applied to `bots/kessoku`) |
| `Submission/bots/kfix3` | Patched copy of kessoku |
| `Submission/bots/zcamp` | Adversary: passive champions park at the nearest altar |
| `Submission/bots/zlock2` | Adversary: kessoku copy that locks every altar |

These are untracked in git. `kessoku.zip` and the tracked source are unchanged (still v18).

Re-run commands, from `Submission/` (use a new TAG each time, build first):

```bash
cambc build kessoku --release && cambc build kfix3 --release
python3 tools/ab.py t1 kessoku zcamp 00elkring 00collision
python3 tools/ab.py t2 kfix3 zcamp 00elkring 00collision
python3 tools/ab.py t3 kessoku zlock2 00fragment 00elkring 00collision 00interlock 00corners 01elk_arena 01hooks 00eight
python3 tools/ab.py t4 kfix3 zlock2 00fragment 00elkring 00collision 00interlock 00corners 01elk_arena 01hooks 00eight
python3 tools/ab.py t5 kfix3 kessoku        # mirror, all 21 maps
```

## Ladder baseline (LADDER, last 90 ranked games)

- Record: 46 wins, 44 losses.
- Maps where we lose: `01hooks` 0/4, `00collision` 0/4, `01fracture` 0/3, `00interlock` 0/2, `00elkring` 1/5, `00contest` 1/4.
- 32 of 44 losses were the opponent reaching 1000 gems first. 12 were 2000-round timeouts.
- Average deaths per game: 33 in losses vs 14 in wins.
- Our draft was the same in 90 of 90 games: varg, Cassi & Issac, stellar, then vendetta/tavi/ryth.
- Opponents placed 16,632 wards (about 185 per game). We placed none.
- Enemy champion kills: Stellar 335 of about 1,400.

## Findings

### F1. Altar siege and flip-flop (MEASURED + LADDER)

- **Where:** `Bot::bank()` (`bot.cpp:1426`), `threatened(a)`, and ghost aging in `assess_threat()` (`GHOST_ROUNDS = 8`).
- **Mechanism:**
  1. A carrier heads to altar A and sees campers, so A is marked threatened.
  2. `bank()` switches to altar B.
  3. En route, A leaves sight and its ghost memory expires after 8 rounds, so A looks safe again.
  4. The carrier turns around. Repeat forever.
  - Separate problem: a champion sitting at 31-35% HP never heals. `retreat_if_hurt` only fires below 30%.
- **Exploit:** Park 2-5 champions next to the nearest altar and do nothing else.
  - `zcamp` (5 passive champions, no farming, no fighting) held kessoku on `00elkring` to 0 gems tributed and a 2000-round finish.
  - Per-champion trace: bags of 40-60, HP stuck at 280-300 (about 31-33% of max), walking back and forth for 450+ rounds.
- **Frequency:** Maps with 2 or fewer altars, or altars far from spawn.
  - Ladder `00collision`: 0/4, with 0, 18, 0 and 74 gems tributed. In one game we collected 957 gems and submitted 0.
  - Ladder `01hooks`: 0/4. 179 of our 210 deaths there (85%) were within 6 tiles of its only altar.
- **Smallest fix:**
  - Per-altar `altar_hot[i] = round` whenever a foe is within `ALTAR_THREAT_RANGE`; treat the altar as threatened for 60 rounds.
  - Heal threshold 50% when calm (no foes, no awake camp within 5, not capturing).
  - 20-round bank embargo after an escape with a bag.
  - Implemented in `kessoku_review_fixes.diff`.
- **Result (MEASURED):**
  - `00elkring` vs `zcamp`: 2000 rounds / 0 gems became 531 and 423 rounds with about 1000 gems.
  - `kfix3` vs current kessoku, all 21 maps both sides: 26/42, deaths 188 vs 283.
  - `kfix3` vs `oldpy`: 42/42, average win round 676 (kessoku: 723).
  - `kfix3` vs `starter-cpp`: 42/42.
  - `kfix3` vs `zcamp`, all maps: 42/42.
  - The three parts were not tested separately.
- **Regression test:** `ab.py` of the patched bot vs `zcamp` on `00elkring`, both sides. Pass: at least 900 gems tributed and under 800 rounds.

### F2. Enemy altar locks are never cleared (CODE + MEASURED)

- **Where:** `bank()` (`bot.cpp:1441`), which does `continue` on an enemy-locked altar. No code calls `attack(altar_lock)`, which the API provides (`BotAPICpp.md`, around line 4752).
- **Mechanism:** A lock has no expiry in the rules and costs 10 gold. Removing it takes 3 basic attacks. We skip that altar forever and fall back to the 25-round bank embargo.
- **Exploit:** `zlock2` is a kessoku copy plus about 20 lines that lock every altar, nearest first. Over 8 maps and both sides it beat current kessoku **14/16**, with tributes of 3,842 vs 14,607.
- **Frequency:** Not visible on the ladder, because match summaries do not log lock placement. Any opponent can buy a lock cheaply.
- **Smallest fix:** In `bank()`, walk to attack range of an enemy-locked altar and call `me.attack(altar_lock_at(a))`. About 15 lines.
- **Result (MEASURED):** Lock clearing plus F3 alone (`kfix`, later merged into `kfix3`) took the result vs `zlock2` from 2/16 to **14/16**. `kfix3` scored 11/16.
- **Regression test:** `kfix3` vs `zlock2` on the 8 maps listed above. Pass: at least 12/16.

### F3. `any_safe` counts unreachable altars (CODE + MEASURED)

- **Where:** `bank()`, the `any_safe` loop. On `00collision` the second altar (39,20) is walled off; my probe reported its distance from both spawns as unreachable.
- **Mechanism:** With one enemy within 6 of the only reachable altar (27,20), `any_safe` is true because of the walled one. The reachable altar is skipped, `move_to` fails on the unreachable goal, and the 25-round embargo triggers. Repeats.
- **Exploit:** Any champion near the central altar on `collision`. With `zcamp`, kessoku on side A needed 2000 rounds for 508 gems. With the fix it needed 401-467 rounds for over 1000 gems.
- **Smallest fix:** Count an altar as a safe alternative only if a tribute tile next to it is reachable from our spawn (about 6 lines).
- **Regression test:** `00collision` vs `zcamp`, both sides. Pass: at least 1000 gems in under 500 rounds.

### F4. Cassi & Issac are a single point of failure (LADDER)

- **Where:** No linked-death handling anywhere in the code. `draft.cpp` scores the pair highest (9.6), so it is picked first every game.
- **Mechanism:** One kill removes both bodies for 60 rounds and pays out both bags (rules: Cassi & Issac section).
- **Evidence:** Pair deaths average 6.1 per game, against 3.1 for Stellar and Varg and 3.8 for Vendetta. The pair accounts for 1,098 of 2,112 body-deaths (52%) while being 2 of about 6 bodies.
- **Exploit:** Stun and burst Cassi (700 HP, ranged). Issac dies with her.
- **Frequency:** Every game.
- **Smallest fix (untested):** Use `min(Cassi HP, Issac HP)` for retreat and danger checks, keep the pair within about 8 tiles, and try a higher retreat threshold for the pair. Alternatively lower the draft score by about 1.5 and A/B it.
- **Regression test:** Staged duel against two enemy champions on fixed seeds. Pass: fewer pair-deaths per game.

### F5. Fuel exhaustion on 100x100 maps (LADDER + MEASURED)

- **Where:** `choose_target()` every 4 rounds (full-map `here.compute`, the detour field, a score per group) and `move_to`.
- **Evidence:**
  - Ladder `01big_world`: 717 fuel-exhausted events per game on our side, over 5 games (all 5 won).
  - Local runs: 313 (side A) and 197 (side B) on `big_world`, 16-18 on `00ambush`.
  - Also high on `00lanes` (about 100) and `01elk_arena` (about 111) on the ladder.
- **Mechanism:** A suspended turn resumes next round, so affected champions act at a reduced rate and can be killed with half a decision made.
- **Smallest fix (untested):** Stagger `choose_target` by body index and cache the distance field between re-scores.
- **Regression test:** `ab.py` vs `zcamp` on `01big_world`. Pass: `fuelExhausted` events drop by at least 10x.

### F6. Melee champions cannot answer ranged pokers (HYPOTHESIS, with data)

- **Where:** `fight_enemies()` only steps toward an enemy that is killable this turn and at exactly distance 2.
- **Why it matters:** A ranged enemy at distance 3 takes free hits while our melee farmer keeps attacking a camp.
- **Evidence:** Enemy Stellar is the top killer on the ladder (335 kills).
- **Smallest fix:** Let melee chase a ranged enemy when allies are within 7 tiles and the power ratio is under 1. `RANGED_CHASE` A/Bs were negative earlier, so test before shipping.

### F7. Smaller items

| # | Item | Label | Fix |
|---|---|---|---|
| a | A dead champion leaves its claim byte set: the dead branch of `play_turn` sets `target = -1` without `write_claim(-1)`. Allies count the dead body as a squad member for 60+ rounds. | CODE | Write 0 on death |
| b | `paid` treats any gold jump of 10 or more as a capture. A +50 kill bounty while standing on a camp tile marks the group captured and broadcasts it. | CODE | Require the group to be in `reward` state |
| c | Wards are never used. Each champion's ward feeds only its owner, so a ward left at an altar would show campers before we walk in. | LADDER (opponent use), benefit untested | Place one at the altar |
| d | Fixed 30% retreat ignores incoming burst. A 6-elk group deals about 360 per round, so a 900-HP champion at 31% (279 HP) can die in one turn. | CODE | Retreat at `max(0.30 x max HP, 1.5 x camp dps)` |
| e | Draft is identical in 90 of 90 games; `COUNTER_DRAFT` is off. | LADDER | Pick opening by map shape |

## Adversary archetypes

| # | Archetype | Targets | Status |
|---|---|---|---|
| 1 | Siege camper: 2-5 champions park on the nearest altar, the rest farm | F1, F3 | Reproduced (`zcamp`) |
| 2 | Locksmith: lock every altar by about round 50 | F2 | Reproduced (`zlock2`, 14/16) |
| 3 | Cassi assassin: stun and burst Cassi to kill both bodies | F4 | Not run |
| 4 | Fuel bully on 100x100 maps: force fights while our turns are suspended | F5 | Not run |
| 5 | Ranged kiter: Stellar/Tavi pokes melee farmers from range 3-4 and never trades | F6 | Not run |
| 6 | Draft counter: our picks are known, so take Stellar early and mirror the AoE answers | F7e | Not run |
| 7 | Capture stealer: step onto a tile of the capture region to reset our 5-round timer | the "hold" logic | Not run |

## Ranked top five and fix order

1. **F1 altar siege and flip-flop.** It froze whole games and probably explains `collision` and `hooks`.
2. **F2 lock clearing.** About 15 lines, 14/16 against the locksmith, and any opponent can do it cheaply.
3. **F3 reachable `any_safe`.** About 6 lines. Ship together with F1 and F2.
4. **F4 Cassi & Issac linkage.** Half of our body-deaths. Needs A/B work.
5. **F5 100x100 fuel.** 717 events per game on `big_world`.

Order:

1. Apply `kessoku_review_fixes.diff` (F1 + F2 + F3).
2. Re-run the 42-game mirror and the `zcamp` and `zlock2` suites.
3. F4, then F5.
4. F6 and F7 last.

## Data sources

- Ladder summaries: `cambc matches summary <id> --json` for 90 of the 100 most recent ranked games of team HighCortisol. They were stored in the session scratchpad, which is temporary, and were not copied into the repo.
- Map geometry: printed by a temporary probe bot (since deleted). `00collision` altars are (27,20) and (39,20); the second is not reachable from either spawn.
