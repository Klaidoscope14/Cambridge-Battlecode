# Ladder patterns: ladder "v27" (internal v28), 2026-10-24

Data: all 1365 ranked games of the ladder-v27 build (2026-10-22 19:30 UTC to 2026-10-24 17:50 UTC),
679-686 (50%). Every game summary was downloaded. Map geometry (camp groups, altars, spawns)
came from a probe bot (`bots/zgeo`). Each gem collection, death and bag loss is attributed to the nearest
map landmark, and every pattern below is counted per distinct opponent, so a single opponent cannot
produce it. Scripts are in the session scratchpad (`lad/`: ev.py, pat.py, pat2.py, cross.py, miss.py,
held.py).

## 1. The map decides most results
The 10 worst maps are 58/339 (17%); the other 30 maps are 621/1026 (61%). On each bad map we lose to
nearly every opponent we meet, so these are map-level weaknesses, not opponent-specific ones.

| map | WR | distinct opps / beat us | collected us/them | deaths us/them | main cause |
|---|---|---|---|---|---|
| 00monolith | 2/30 | 25 / 24 | 790/1059 | 18.9/4.0 | they take monoliths, kill us mid-map |
| 00lost_world | 3/35 | 29 / 26 | 548/1018 | 20.4/11.7 | they win the centre gem-cluster race 2:1 |
| 00lanes | 4/38 | 31 / 29 | 747/1061 | 19.4/4.7 | they invade our half, kill us at our altars |
| 01starfish | 3/23 | 21 / 18 | 401/1077 | 45.7/14.8 | we die to the centre elk group (bug, sect. 2) |
| 00collision | 4/29 | 28 / 24 | 740/1058 | 11.5/2.8 | invasion + bag losses at our gold clusters |
| 00elkring | 7/40 | 33 / 26 | 894/1057 | 12.5/4.8 | theft (29/game), bags lost in the open |
| 00contest | 6/33 | 28 / 23 | 97/467 | 52.0/11.5 | gem-dead map: we feed kills, lose gold tiebreak |
| 00great_wall | 10/48 | 40 / 32 | 993/1115 | 9.9/8.4 | bag losses 223/game |
| 01starvation | 8/27 | 24 / 18 | 632/759 | 25.9/11.9 | monoliths + theft (49/game) |
| 00corners | 8/27 | 24 / 18 | 829/972 | 9.6/2.2 | close farming race, we die 4x as often (not dug into) |

On monolith, lanes and collision, each side farms its own half about equally. The gap comes from what
happens in the middle and on our half: they kill us there 4-5x as often as we kill them, and steal 22-25
gems a game from our clears (we steal 6).

## 2. Bug: walking through awake camps (01starfish, reproducible locally)
- Starfish's only two altars, (23,17) and (26,17), sit inside the 118-gem group (6 elks at x 24-25,
  y 16-18, reach 4). As side B we die 54 times a game, 27.5 of them at that group, and 15 a game are
  kills by the camp itself, across 14 different opponents. As side A it is about 3 camp kills a game.
- Locally v28 also dies 40-53 times as side B vs 9-14 as side A (zmeta/zdive/zpoke), and those
  opponents, which are forks of our engine, die 50+ times when they are on side B.
- Replay frames: a full-HP, 0-gem champion alone walks east→west at (29,20)→(25,20), past elks that
  are already awake (HP below 2400), and drops to 4% HP within 4 rounds.
- Cause: `Bot::ensure_danger()` (bot.cpp ~918) and `burst_at()` count only enemy champions and
  remembered enemies. Awake camps never mark tiles as dangerous, so `move_to` paths through their reach.
- Fix to test: add awake (damaged or attacking) camps' reach squares to `danger` when that group is
  not our target. A/B on starfish both sides, then the full pool.

## 3. Monolith gems are conceded on every map that has them
- Per game: monolith gems us 4, them 41. Golems go our way, 34 vs 14.
- Opponents' monolith take per game: contest 467, gold_rush 322, boss_battle 277, monolith 94,
  broken_curve 67, starvation 59, big_world 44, fracture 40, rows 40.
- On maps with a monolith, our win rate is 31% (31/101) when the opponent takes one and 53% (258/489)
  when nobody does.
- Earlier local tests (MONOLITH_WHEN_DOMINANT, VULTURE) failed because our mirror bots finished what we
  started. The ladder field takes monoliths whatever we do, so the local test setup mis-measured this.
  Worth re-testing against an adversary that kills monoliths, with vulture-style capture of
  monoliths the enemy has softened.

## 4. Gem-dead maps are lost on deaths (contest)
- 19 of the 87 losses at round 2000 were 0-0 ties decided on gold, 15 of them on contest.
- In those games we die 55-90 times against 0-9, and their gold is 12-23k against our 3-8k
  (kill gold is 100).
- 7.2 deaths a game happen at our own spawn and 16 in the open: we get spawn-camped. Locally contest is
  a win, so only the ladder shows this.

## 5. Wins left on the table: unbanked team totals
- In 38 of 599 losses that ended at the enemy's 1000, our tributed plus carried gems were already
  ≥1000.
- In 32 of them (outside boss_battle) the team total crossed 1000 6-217 rounds (median ~40) before
  the loss, spread over several 30-80 gem bags. The v28 winning-bag rule only fires for a single
  bag that wins alone. A team close-out (when tributed + visible allies' bags ≥ 1000, every carrier
  ≥10 banks) is worth up to about +2.8% win rate.
- boss_battle (13 losses): the only altar opens once the boss monolith dies. Opponents kill it first
  in most games and tribute at once, while we sit on 700-3900 carried gems; `BLOCKED_ALTAR_FARM`
  turns banking off for 25 rounds and does not react when the boss dies. Fix: re-enable banking the
  moment the boss camp is seen dead.

## 6. Capture theft
Opponents collect 23 gems a game from groups we cleared, against our 14 from theirs. The worst maps
are elk_arena (105 vs 33), corridors (98 vs 60), starvation (49 vs 14), elkring (28 vs 10),
lost_world (26 vs 11) and lanes (23 vs 6).

## Side asymmetry
Overall A 47.2% vs B 52.5%. Starfish (A 4/9, B 0/15, z=+2.8) is the one significant gap that is ours;
three B-favoured maps at z≈-2 are within chance for 40 maps.
