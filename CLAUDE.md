# CLAUDE.md — handoff for any agent working in this repo

Read this first. It is the authoritative summary of state, rules and testing protocol (as of 2026-10-28).
`Research.md` is the full log of every measurement; `README.md` is the human overview. Where `Submission/SUBMIT.md`
disagrees with this file (it has stale version names), this file wins.

## 1. What this is

A C++ bot for the CAMBC '26 Autumn champions game (`cambc` 4.0.0, engine 2.0.0 — the latest release; rules in
`GameRules.md`, C++ API in `BotAPICpp.md`, both current). Ladder team **HighCortisol** (team id
`58271d23-d86a-48de-987a-5d82c983d7db`). First team to tribute 1,000 gems wins; at round 2,000: tributed gems, then
lifetime gold, then kills.

## 2. Hard rules (from the user)

1. **Never upload or activate anything.** No `cambc submit`, no `cambc submissions activate`. Build the zip at the repo
   root (`kessoku.zip`) and tell the user; the user uploads, activates and rolls back.
2. **Never change the live bot in place.** `Submission/bots/kessoku` = `Submission/bots/v65` = ladder v44 (live). Work in
   a copy (e.g. `bots/v70`) behind `Cfg::` switches that default to off.
3. **Follow the testing protocol below exactly** (the user insists on it). No nova-vs-nova or mirror-only acceptance.
4. **No map or opponent hard-coding.** Rules must be general game features validated on the full pool.
5. **Record every result in `Research.md`** (section 6 table "Measured and rejected", or the ladder sections). Do not
   create new top-level .md files for findings.
6. **Clean up after runs**: delete variant bots (`bots/v7x*`), probe bots and stale run folders when a test is done.
7. Do all work in one session unless the user asks for parallel sessions.
8. AWS: always make sure no instance is left running (`aws ec2 describe-instances --filters
   Name=instance-state-name,Values=pending,running`); terminate leftovers.

## 3. Current state (2026-10-28)

| Bot (in `Submission/bots/`) | Status |
|---|---|
| `kessoku` = `v65` | **Live (ladder v44).** v61 + CI_DRAFT (Cassi & Issac first) + MONO_AVOID. Full pool 1,471 vs v61's 1,398; panels 22/40 (best). 412 ranked games: 52%. |
| `v70` | Switch lab on v65: ~24 review-proposed fixes, **all off == v65 (verified bit-identical)**. Every one was tested and rejected; see Research.md section 6 (rows "v70 review fixes", "v71 review part 3", "zhunt", "Review part 4"). |
| `v67` | v65 + THREAT_BANK8 + RACE_SOLO + FIGHT_SIM_OUTMATCHED — rejected on panel B (ladder v45, rolled back). |
| `v61`, `v59ns`, `v59oh`, `v58pl`, `v57br`, `v54po`, `v47h25` | Older versions / rollbacks. |
| `nova` | From-scratch bot (`NewStrategy.md`, `Observations.md`). Far weaker than v65 (0/12 head to head, nova vs v65 full pool 61 vs 338 wins). Accepted nova switches: ALIVE_STATE, DEAD_SHOP, MOVE_RESET, JOIN_AT, EARLY_OUT. |
| `z*` | Local test opponents (section 5). `zhunt` (newest) is the closest to ladder behaviour. |
| `starter-cpp`, `starter-python` | Starter bots. |

Key findings (details in Research.md):
- v65's ladder losses are **fights, not farming**: deaths 23.2 vs 4.8 in losses (9.9 vs 10.6 in wins); gems collected by
  r300 equal. 57% of loss deaths are isolated pick-offs, often 2-on-1 on our half; victims go 76 → 66 → 48 → 20% HP over
  8 rounds. adgato_gemcombat maps (all gem clusters, 0 gold) 6/41, elkring 1/10, gold_rush 1/6.
- The **local pool is far weaker than the ladder**: v65 wins 72–100% against every z* bot (88% overall) vs 52% ranked.
  Local tests guard against harm; they cannot prove a fight improvement. Every review fix (economy, pick-off leash,
  escape support, camp-gank guard, Marcella opener, draft changes, gold weights, banking/shopping thresholds) came out
  level or negative on the full pool.
- Copying the top-10 draft (Marcella/Vesper/Vendetta/Heart) failed twice (600 vs 674, 603 vs 674) and again as
  MARCELLA_OPENER. Don't retry without a new idea.

## 4. Testing protocol (do exactly this)

Every candidate change is a `Cfg::` switch (`inline constexpr bool X = false;` in `common.h`) in a copy of the live bot.

1. **Identity check.** With the switch off the copy must play **bit-identically** to the live bot:
   `python3 tools/ab.py idA COPY zmarc 00eight 02fields 01shortcut 00lanes 00elkring adgato_gemcombat4` and the same with
   `v65` — the SUMMARY lines must match exactly. Gate all new code behind `if (Cfg::X ...)` / `if constexpr`; even unused
   code that spends fuel shifts timing and changes games (measured: gold@300 955 → 915 from timing alone).
2. **Focused test.** The change's target maps against 2–3 relevant opponents, one setting, ~84–300 games, paired with
   `tools/sprt.py`. Must be **level or better** (wins gained ≥ wins lost). Typical sets:
   - fight changes: 14 fight maps `00lanes,00quarry,01gold_rush,00monolith,00reverse_spiral,02the_pack,02famine,02guardians,00lost_world,01the_farm,adgato_gemcombat1,02uncharted_lands,00elkring,00vault` vs `zmarc,zgank,zhunt` (or `zci`);
   - economy changes: 24 maps `00anvil,00contest,00corners,00elkring,00lost_world,00monolith,00quarry,00reverse_spiral,00the_line,00vault,01fracture,01gold_rush,01shortcut,01the_farm,02arena,02fields,02gift_wrapping,02guardians,02stalactites,02the_pack,02treasure_box,02uncharted_lands,adgato_gemcombat1,adgato_gemcombat4` vs `zmarc,zgank,zmeta`;
   - altar/lock changes: same 24 maps vs `zlock2,zcamp,zmarc`.
3. **Full-pool non-regression.** All 70 maps × both sides × 12 opponents
   `zmarc,zgank,zmeta,zpoke,zdive0,zhor,zrush,zstack,zmono2,zlock2,zcamp,zci` = 1,680 paired games
   (`--max 1680 --alpha 1e-9 --beta 1e-9`). Passes unless clearly worse: **net (+ minus −) ≥ −2·√(+ plus −)**. Also run
   the candidate vs `zhunt` (140 games). Useful extra breakdown: bruiser bots (zstack/zgank/zmarc/zhunt) and pure race
   maps (00rows/00galaxy/00split).
4. **Real opponents (user step).** Bundle `kessoku.zip` from the candidate, back up the current zip, hand it to the user.
   After the user uploads and it is live: Panel A (diagnostic) `python3 tools/panel.py run LABEL`, then Panel B (held
   out, accept/reject) `python3 tools/panel.py --panel tools/data/panel_holdout.json run LABEL`. Panels play the LIVE
   submission only. Never accept a change from the panel it was designed on (A). Ladder over 100+ games is final.
   If a combined change is rejected: test the full combination first, then single switches.

Paired results: "+" = games only the variant won, "−" = games only the base won. A mirror win is not evidence.

## 5. Local opponents (v65's baseline win rate, 140 games each)

| Bot | Archetype | v65 wins |
|---|---|---|
| zci | always drafts Cassi & Issac | 72% |
| zstack | melee bruisers (Heart/Marcella/Ryth/Vendetta/Vesper), stacking | 76% |
| zgank | dive draft, chases weakened enemies within 6 | 77% |
| zmarc | ladder-team draft (Heart/Marcella/Ryth/Vesper/Willow), chase + invade | 81% |
| zmono2 | monolith taker | 85% |
| zdive0 | dive draft, no chase | 87% |
| zpoke | ranged kiter (Vesper/Tavi/Willow) | 91% |
| zrush | early rush (Ren/Stellar/C&I/Varg/Ryth) | 94% |
| zmeta | old ladder-meta copy | 94% |
| zhor | C&I/Heart/Stellar/Varg/Vendetta | 95% |
| zlock2 | altar-lock user | 98% |
| zcamp | altar camper, never tributes | 100% |
| **zhunt** | v65 engine + top-10 draft + `hunt()` of isolated enemies + help calls + raids | **79% (hardest; ladder-like losses)** |

## 6. Commands (run from `Submission/`)

```bash
pip install cambc==4.0.0          # same version as the ladder; Linux wheel exists
cambc login                       # user must do this (interactive); needed for ladder, matches, panels
cambc build BOT                   # build; after any cambc upgrade delete every bots/*/.cambc first
python3 tools/ab.py TAG BOT OPP [maps...]          # quick local games, both sides; AB_OUT=dir keeps results
python3 tools/sprt.py VARIANT BASE OPP1,OPP2 --maps m1,m2 --max N --alpha 1e-9 --beta 1e-9   # paired A/B, cached per source hash
python3 tools/aws_runner.py batch FILE             # sprt lines on a 192-vCPU AWS spot instance (~25x); needs AWS creds
python3 tools/aws_runner.py ab VARIANT BASE OPPS [sprt args]   # one test; pulls per-game results
python3 tools/panel.py run LABEL [--panel tools/data/panel_holdout.json]
python3 tools/ladder_compare.py NAME=START_UTC ... # ladder win rates by version
rm -f ../kessoku.zip && cambc bundle kessoku --output ../kessoku.zip
```

Environment notes:
- macOS dev machine quirks: tool shell lacks `/opt/anaconda3/bin` in PATH (prefix it); `sed -i ''` is BSD — use
  `sed -i.bak` for portability.
- AWS runner: region ap-south-1, spot `c7i.48xlarge` (falls back to other types), key pair `kessoku-runner`
  (private key `~/.ssh/kessoku-runner.pem` lives only on the user's Mac — on a new machine either copy it or delete the
  AWS key pair so the runner recreates it), SSH-only security group `kessoku-runner`. It terminates the instance after a
  batch; if you kill the runner, terminate the instance yourself. Per-game results are only kept if the runner reaches
  its pull step. AWS needs the user's credentials (`aws login`); a cloud session may not have them — then run locally
  (`tools/sprt.py`, `JOBS=8`), ~40 games per 5 min on 8 cores.
- sprt cache: `$TMPDIR/kessoku_sprt/<bot>-<hash>/OPP_MAP_SIDE.json` (per-game summaries for breakdowns).
- Fuel: ~100k per turn; thrown engine errors cost ~2K; `vision::camps()` ~10K with 40+ camps; prints ~3K. Exhausted
  turns are suspended (`fuelExhausted` events in the stats JSON).

## 6b. Running in a cloud session

Nothing below carries over from the user's Mac automatically; check each before relying on it.

1. **First check (run these before any analysis or test):**
   ```bash
   pip install cambc==4.0.0 && cambc --version     # must print 4.0.0
   node --version && python3 --version             # replay reader needs Node; tools need Python 3
   cambc matches list --team me --kind ranked --limit 1 --json   # works only when logged in
   aws sts get-caller-identity                     # works only with AWS credentials
   ```
2. **cambc login.** Try `cambc login` in the session (it lasts 7 days). If it cannot complete without a browser, ask the
   user to provide the session file from their Mac (`~/Library/Application Support/cambc/session-*.json`) as a secret
   and write it where Linux cambc reads it (likely `~/.config/cambc/`; unverified — check `cambc login` behaviour).
   Treat that file as a password. Without a login: local matches and tests still work; ladder, match downloads and
   panels do not.
3. **AWS.** Needs credentials as environment variables / secrets in the cloud environment (`AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION=ap-south-1`), ideally a dedicated IAM user limited to EC2 in ap-south-1.
   The runner SSHes with key pair `kessoku-runner`; its private key exists only on the user's Mac. Either the user
   supplies it as a secret (write it to `~/.ssh/kessoku-runner.pem`, `chmod 600`), or the `kessoku-runner` key pair is
   deleted in AWS so the runner recreates it. The runner opens the security group to the current public IP itself.
4. **Network.** The environment must allow outbound access to the CAMBC platform API, the AWS endpoints and SSH (port
   22) to EC2 instances. If SSH is blocked, AWS runs fail even with credentials: run tests locally with
   `tools/sprt.py` instead (much slower).
5. **Paths.** Analysis scripts use repo-relative paths; caches go to `~/.cache/...` and `$TMPDIR/kessoku_sprt`, which
   start empty in a new session (baselines are replayed once, then cached).

## 7. Analysis tools and data in the repo

| Path | What |
|---|---|
| `Submission/tools/analysis/replay/rp.js` + `engine_v2_0_0.wasm` | Read replay state in Node via the engine wasm (snapshot layout in the header). |
| `.../replay/deathctx2.js` | Victim/ally/enemy state at t−8..t−2 before each death of a team. |
| `.../replay/earlytime.js` | Time split (camp fight, walk, capture, spawn, wait, dead) for rounds 0–300. |
| `.../replay/observe2.js`, `summ_detail.py`, `run2.py` | Behaviour profiling used for `Observations.md`. |
| `Submission/tools/analysis/ladder/v44_rows.py` | Per-game rows (deaths, gold@300, clears, killers, half) from ranked match summaries. |
| `Submission/tools/analysis/ladder/top10_extract.py` | Top-10 teams' per-game rows. |
| `Submission/tools/analysis/thr.py` | Throughput metrics (gold/gems/clears @300/600) for ab.py runs. |
| `Submission/tools/analysis/flagtest.sh`, `mk_novat.py`, `mk_novad.py` | nova switch tests (mirror method, nova only) and nova fuel/death trace builds. |
| `Submission/tools/data/ladder/` | `v44_rows.json` (412 v65 ranked games), `v44_list.json`, `top10_rows.json` (2,500 top-10 games), `top10_lists.json`, `v44_loss_deaths.json` (512 deaths, t−8..t−2), `early_time_split.json`. |
| `Submission/tools/data/geo.json`, `spawns.json`, `pool.txt`, `panel*.json` | Map geometry for all 70 maps, spawns, ladder pool, the two panels. |

Download a match: `cambc matches download <matchId>` (zip with `replay.repl26a` and both teams' stdout); summary:
`cambc matches summary <id>` then `cambc summary file.camstat -o out.json`.

## 8. Ideas not yet tried (from the last analyses)

- Fights decide losses, and single-switch fight tweaks don't move v65. Next ideas need a bigger structural change:
  moving/farming in pairs on fight maps, or a real fight-outcome model (FIT_FIGHT exists, fitted on older data).
- A stronger ladder-like adversary than zhunt (it beats v65 only 21%) would make fight tests meaningful.
- Top-10 spend ~8% of early time at spawn (v65 2.5%) and ~8 points less time walking.
