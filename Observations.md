# How the top-10 teams play (CAMBC '26, engine 2.0) — observations

Compiled 2026-10-27. Purpose: the factual basis for a new bot written from scratch. Everything here is measured;
interpretation is kept to the last section. "Us" = our v41 + v43 ranked games (kessoku), unless stated otherwise.

## 1. Data and method

| Source | What | Size |
|---|---|---|
| Match lists | Top-10 teams' 250 most recent ranked matches each (27 Oct 02:40-10:50 UTC) | 2,500 matches |
| Game summaries (`cambc matches summary`) | Events with round and tile (clears, kills, deaths, tributes, purchases, wards, consumables), per-champion metrics, gold/gem timelines | 2,469 top-10 games, 175 of ours |
| Replays (engine-2.0 wasm in Node) | Full state every 3 rounds to r1,200: every champion's tile, HP, bag, alive; every camp's HP | 60 top-10 games (6 per team, 6 different maps each), 30 of ours |
| Map geometry (`tools/data/geo.json`, `spawns.json`) | Camp groups (gems, gold, kinds, strength), altars, spawns | all 70 maps |

Definitions used throughout:
- **Phase:** early = rounds 0-299, mid = 300-599, late = 600+.
- **Half:** a tile is "own" if nearer the team's spawn than 0.8x the distance to the enemy spawn, "away" in the reverse
  case, else "mid" (replays use the 40/60% split of the distance between the two spawns).
- **Map type:** spawn-to-spawn distance <= 35 tiles = fight map, >= 70 = race map, else normal.
- **Camp kinds:** cluster = monster-free gem/gold cluster (strength 0), small = wolf groups (strength <= 40),
  big = elk/golem groups, mono = monolith (20,000 HP, 200 gems + 300 gold).
- **Contact:** an enemy champion within 5 tiles. **Approach/retreat/hold:** the change in distance to the nearest
  enemy over the next sample.

## 2. The teams

| Rank | Team | Rating | Win rate in sample | Bodies/game |
|---|---|---|---|---|
| 1 | Intercontinental Fish | 2,433 | 69% | 5.3 |
| 2 | Mite | 2,393 | 61% | 4.7 |
| 3 | Trzy Kwaterki | 2,327 | 54% | 4.5 |
| 4 | German Empire Destroyer Destroyers | 2,304 | 50% | 4.4 |
| 5 | NEETCoders | 2,287 | 52% | 4.5 |
| 6 | prism best girl | 2,272 | 48% | 4.4 |
| 7 | Claudus Maximus | 2,258 | 47% | 4.5 |
| 8 | hello | 2,240 | 48% | 4.4 |
| 9 | Ad Astra | 2,239 | 46% | 4.4 |
| 10 | Supaswag | 2,196 | 52% | 4.3 |

Most of their games are against each other, so win rates near 50% are expected; Fish and Mite stand out.
Team sizes across these games: 5 champions 1,487, 4 champions 578, 3 champions 435.

## 3. Draft

Pick rate (share of games the champion is on the team), all top-10 games:

| Marcella | Vesper | Vendetta | Heart of Ruin | Ryth | Tavi | Prism | Cassi & Issac | Willow | Varg | Ren |
|---|---|---|---|---|---|---|---|---|---|---|
| 84% | 82% | 80% | 79% | 42% | 20% | 18% | 11% | 11% | 9% | 1% |

Per team (top picks, share of games; first pick):

| Team | Core | First pick |
|---|---|---|
| Intercontinental Fish | Heart 100, Vesper 100, Vendetta 86, Cassi & Issac 82, Marcella 49 | Vesper 100% |
| Mite | Vendetta 100, Vesper 100, Heart 100, Marcella 56, Tavi 56, C&I 25 | Vesper 100% |
| Trzy Kwaterki | Vendetta 100, Ryth 100, Marcella 100, Vesper 86, Heart 55 | Marcella 95% |
| German Empire DD | Vendetta 100, Marcella 100, Heart 95, Prism 82, Willow 57 | Prism 82% |
| NEETCoders | Heart 100, Vesper 98, Vendetta 95, Marcella 86, Ryth 68 | Heart 100% |
| prism best girl | Prism 100, Heart 87, Marcella 87, Vesper 85, Ryth 60 | Prism 98% |
| Claudus Maximus | Vendetta 100, Heart 100, Vesper 100, Marcella 64, Tavi 41, Ryth 40 | Vesper 100% |
| hello | Marcella 100, Vendetta 98, Tavi 98, Ryth 79, Vesper 56 | Vesper 56% |
| Ad Astra | Heart 100, Vesper 100, Marcella 100, Ryth 80, Varg 56 | Heart 100% |
| Supaswag | Vendetta 100, Vesper 100, Marcella 100, Heart 56, Willow 52 | Marcella 81% |

- First picks overall: Vesper 36%, Marcella 21%, Heart 20%, Prism 18%.
- 3-champion maps: Heart/Vendetta/Vesper (118 games), Heart/Marcella/Vesper (95), Marcella/Tavi/Vendetta (58),
  Marcella/Vendetta/Vesper (54), Marcella/Ryth/Vendetta (35).
- Both teams may draft the same champion (mirror picks are common).
- Ours: Vesper, Tavi, Willow, Varg (+ Stellar / Vendetta / Ryth), and Cassi & Issac since v65. Three of our four core
  picks are among their four least-picked.

## 4. Economy timeline

Team gold earned by round (average per game) and the opponent's gold at r300:

| Team | g100 | g200 | g300 | g600 | Opp g300 |
|---|---|---|---|---|---|
| Intercontinental Fish | **434** | 910 | **1,465** | 3,292 | 1,087 |
| Mite | 291 | 673 | 1,121 | 2,688 | 1,122 |
| Trzy Kwaterki | 345 | 797 | 1,288 | 2,988 | 1,258 |
| German Empire DD | 284 | 622 | 1,023 | 2,415 | 1,247 |
| NEETCoders | 337 | 773 | 1,250 | 2,897 | 1,277 |
| prism best girl | 346 | 751 | 1,216 | 2,810 | 1,232 |
| Claudus Maximus | 336 | 755 | 1,208 | 2,747 | 1,262 |
| hello | 290 | 703 | 1,170 | 2,781 | 1,142 |
| Ad Astra | 331 | 752 | 1,229 | 2,921 | 1,213 |
| Supaswag | 327 | 757 | 1,258 | 3,067 | 1,243 |
| **Us (v41+v43)** | — | — | **~940** | ~2,000 | ~930 |

Event timing in top-10 games (median round of the team's first one): **first camp clear r19, first purchase r57, first
tribute r77, first kill r173.**

Per-phase activity per game (whole team):

| Phase | Top-10 clears | Our clears | Top-10 tributes (gems) | Our tributes (gems) | Top-10 kills / deaths | Our kills / deaths |
|---|---|---|---|---|---|---|
| Early (0-299) | **14.8** | 9.3 | 4.2 (123) | 4.2 (147) | 1.6 / 1.9 | 1.5 / 2.3 |
| Mid (300-599) | **14.9** | 9.6 | 6.0 (222) | 5.4 (191) | 2.1 / 2.4 | 1.8 / 2.5 |
| Late (600+) | 19.9 | 23.1 | 9.9 (417) | 11.9 (437) | 4.2 / 4.4 | 4.5 / 6.4 |

Totals per team (whole game): clears 42-59, tributes 14-25, gems lost to deaths 105-252, wards 77-231.

## 5. Roles: who earns, farms, banks and fights

Per champion, per game in which it was drafted (summaries; top-10 n = games):

| Champion (n) | Gold | g100 / g300 / g600 | Clears: cluster / small / big / mono | Clears: own / mid / away | Clears: early / mid / late | Tributes x avg | Kills / assists / deaths | Gems lost | Champ dmg done / taken | Monster dmg | Wards |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Vesper (2,040) | 2,190 | 139 / 489 / 1,105 | 4.6 / 3.5 / 4.2 / 0.12 | 7.3 / 4.1 / 1.1 | 3.5 / 3.7 / 5.3 | 5.6 x 43 | 2.4 / 3.2 / 1.7 | 56 | 10,351 / 7,230 | 29,601 | 32 |
| Marcella (2,085) | 1,783 | 90 / 350 / 857 | 4.0 / 2.6 / 3.3 / 0.03 | 6.0 / 3.0 / 0.9 | 2.9 / 3.0 / 4.0 | 5.4 x 41 | 2.4 / 2.9 / 1.7 | 37 | 9,291 / 6,419 | 21,043 | 29 |
| Vendetta (1,981) | 1,221 | 71 / 256 / 601 | 5.1 / 3.9 / 4.0 / 0.06 | 7.9 / 4.1 / 1.2 | 4.0 / 3.9 / 5.3 | 5.4 x 35 | 1.9 / 2.7 / 2.1 | 35 | 5,986 / 7,018 | 25,458 | 32 |
| Prism (451) | 988 | 54 / 194 / 490 | 5.6 / 2.9 / 4.0 / 0.09 | 7.4 / 4.3 / 0.9 | 3.9 / 3.9 / 4.8 | 0.4 x 136 | 2.1 / 3.2 / 1.7 | 70 | 7,508 / 3,034 | 28,250 | 22 |
| Heart of Ruin (1,964) | 859 | 49 / 185 / 431 | 6.2 / 2.3 / 2.1 / 0.02 | 6.2 / 3.4 / 1.1 | 3.3 / 3.2 / 4.2 | 4.5 x 32 | 1.3 / 3.5 / 1.7 | 20 | 4,621 / 8,702 | 17,037 | 33 |
| Ryth (1,064) | 686 | 42 / 156 / 356 | 3.9 / 2.4 / 2.6 / 0.02 | 5.4 / 2.8 / 0.7 | 2.7 / 2.7 / 3.4 | 3.0 x 35 | 0.9 / 4.3 / 2.0 | 21 | 4,799 / 6,352 | 17,966 | 29 |
| Tavi (498) | 616 | 41 / 148 / 323 | 5.8 / 3.6 / 2.3 / 0.03 | 6.5 / 3.9 / 1.3 | 3.7 / 3.5 / 4.5 | 3.0 x 27 | 1.0 / 3.4 / 2.5 | 26 | 5,423 / 4,089 | 17,315 | 31 |
| Varg (243) | 543 | 16 / 95 / 253 | 3.5 / 2.2 / 2.9 / 0.00 | 5.5 / 2.6 / 0.5 | 2.2 / 2.7 / 3.7 | 1.9 x 35 | 0.5 / 2.5 / 1.6 | 23 | 2,770 / 5,508 | 22,243 | 23 |
| Issac (282) | 437 | 32 / 109 / 239 | 3.7 / 1.4 / 1.6 / 0.01 | 3.9 / 2.4 / 0.5 | 2.0 / 2.2 / 2.6 | 2.4 x 27 | 0.6 / 3.4 / 3.4 | 20 | 1,423 / 2,785 | 10,313 | 31 |
| Cassi (282) | 339 | 29 / 84 / 193 | 4.4 / 1.3 / 1.7 / 0.00 | 4.4 / 2.1 / 0.7 | 2.3 / 2.3 / 2.7 | 1.9 x 27 | 0.9 / 4.5 / 3.4 | 19 | 3,352 / 1,779 | 11,299 | 29 |
| Willow (278) | 257 | 16 / 55 / 124 | 4.0 / 2.0 / 1.7 / 0.01 | 4.8 / 2.5 / 0.4 | 2.6 / 2.6 / 2.5 | 2.0 x 20 | 0.2 / 2.3 / 2.2 | 7 | 967 / 1,995 | 10,962 | 17 |

Ours, same columns (175 games):

| Champion (n) | Gold | g100 / g300 / g600 | Clears: cluster / small / big | Clears: own / mid / away | Clears: early / mid / late | Tributes x avg | K / A / D | Gems lost |
|---|---|---|---|---|---|---|---|---|
| Vesper (175) | 3,114 | 172 / 499 / 1,157 | 2.6 / 2.1 / 6.6 | 6.5 / 3.4 / 1.4 | **2.0 / 2.3** / 7.0 | 9.3 x 42 | 3.5 / 2.5 / 1.9 | 36 |
| Varg (175) | 1,144 | 50 / 170 / 390 | 3.6 / 2.2 / 4.4 | 5.9 / 3.1 / 1.2 | 2.0 / 2.2 / 5.9 | 5.0 x 32 | 0.8 / 3.1 / 2.8 | 31 |
| Stellar (58) | 898 | 18 / 101 / 266 | 3.1 / 1.3 / 3.6 | 5.4 / 1.7 / 0.8 | 1.9 / 1.7 / 4.3 | 2.1 x 34 | 1.7 / 4.2 / 2.4 | 29 |
| Tavi (175) | 765 | 35 / 142 / 288 | 3.3 / 2.6 / 4.5 | 6.1 / 3.0 / 1.3 | 2.7 / 2.5 / 5.3 | 3.3 x 33 | 2.0 / 3.6 / 2.4 | 23 |
| Vendetta (37) | 561 | 30 / 138 / 273 | 2.9 / 1.8 / 3.3 | 4.6 / 2.9 / 0.6 | 2.2 / 2.1 / 3.7 | 4.6 x 29 | 0.9 / 2.3 / 3.0 | 8 |
| Willow (148) | 469 | 22 / 73 / 175 | 2.7 / 1.1 / 2.5 | 3.5 / 2.0 / 0.9 | 1.7 / 1.6 / 3.0 | 2.2 x 30 | 0.7 / 3.6 / 2.9 | 16 |

Top earner per game (900 top-10 games): Marcella 375, Vesper 253, Vendetta 171, Heart 51, Prism 27, Tavi 9.
Share of team gold taken by the top earner: 41-56% (us 55%).

## 6. Farming: openings, routes and where they spend time

First three camp clears of each champion (most common sequences, top-10):

| Champion | 1st | 2nd | 3rd |
|---|---|---|---|
| Vesper | cluster/own x3 (165) | small/own x3 (103) | big/own x3 (92) |
| Marcella | cluster/own x3 (134) | big/own x3 (114) | small/own x3 (96) |
| Vendetta | cluster/own x3 (154) | small/own x3 (112) | big/own x3 (81) |
| Heart | cluster/own x3 (187) | cluster/mid x3 (97) | big/own x3 (70) |
| Ryth | cluster/own x3 (84) | cluster/mid x3 (48) | big/own x3 (46) |
| Ours: Vesper | **big/own x3 (15)** | big/mid x3 (11) | cluster > small > big (7) |
| Ours: Tavi | big/own x3 (13) | cluster/own x3 (8) | big/mid x3 (8) |
| Ours: Varg | big/own x3 (11) | cluster/mid x3 (8) | big/mid x3 (7) |

Where champions spend rounds 0-1,200 (replays; share of alive samples; "farm" = within 2 tiles of a live camp):

| Champion | Dead | At spawn | Own / mid / away | Within 4 of ally | > 8 from any ally | Avg bag | Avg HP | Farming |
|---|---|---|---|---|---|---|---|---|
| Heart | 10.1% | 2.9% | 50 / 44 / 6 | 50% | 31% | 13.2 | 84% | **33%** |
| Vendetta | 11.0% | 3.5% | 55 / 42 / 3 | 45% | 34% | 16.4 | 83% | 29% |
| Vesper | 7.8% | 6.6% | 57 / 37 / 6 | 49% | 31% | 18.3 | 86% | 18% |
| Marcella | 8.8% | 5.0% | 55 / 39 / 6 | 49% | 31% | 17.9 | 87% | 26% |
| Ryth | 10.2% | 4.3% | 55 / 40 / 5 | 49% | 34% | 14.6 | 84% | 29% |
| Prism | 8.3% | 4.8% | 52 / 44 / 4 | 56% | 23% | **78.2** | 92% | 14% |
| Cassi / Issac | 20.6% | 16.8 / 10.0% | 47 / 47 / 6 | 73% | 12-16% | 2-6 | 83-91% | 8 / 21% |
| Ours: Vesper | 6.3% | 2.6% | 54 / 44 / 3 | 46% | 32% | 22.5 | 86% | 14% |
| Ours: Tavi | 8.5% | 2.5% | 54 / 42 / 4 | 62% | 20% | 13.0 | 87% | 12% |
| Ours: Varg | 11.8% | 2.4% | 57 / 39 / 4 | 48% | 34% | 14.1 | 83% | 27% |
| Ours: Willow | 10.6% | 3.3% | 56 / 40 / 4 | 62% | 22% | 6.9 | 88% | 10% |

By phase (replays, whole team):

| Phase | Top: within 4 of ally | Top: > 8 alone | Top: farming | Top: at spawn | Ours: within 4 | Ours: > 8 alone | Ours: farming | Ours: at spawn |
|---|---|---|---|---|---|---|---|---|
| Early | 61% | 22% | **26%** | 5.3% | 66% | 19% | 17% | 2.3% |
| Mid | 49% | 31% | 25% | 4.5% | 52% | 27% | 18% | 2.8% |
| Late | 43% | 37% | 22% | 5.7% | 49% | 31% | 14% | 2.8% |

Clears by camp kind and side, per game (team): clusters 17-33 (largest share), small 10-19, big 12-16, monoliths
0.06-0.37; own half 28-43, away 13-21. In their comeback wins they clear away more (16.8 vs 12.8 for the leader).

## 7. Banking

- Tribute size (all top-10 tributes): early median 21 / mean 27 (n 6,413); mid median 25 / mean 34 (8,604); late median
  26 / mean 38 (12,695). Bags are small and frequent.
- Tributes per game 14-25; average gem bag carried 17 (ours 11.6 in the same replay sample). Prism is a carrier
  (bag averages 78, 0.4 tributes a game of 136 gems).
- Marcella gets 2 gold per gem she tributes (engine constant `marcella_tribute_gold_per_gem = 2`); she tributes 5.4 a
  game x 41 gems: ~440 gold a game from tributes alone.
- First tribute at r77 (median): they bank the first small bag early instead of farming up a big one.

## 8. Items and shopping

First three emblems completed, most common per champion (top-10):

| Champion | Most common | Second | Third |
|---|---|---|---|
| Marcella | Treasure Health > Jungle Strength > Bruiser Health (112) | Monster Focus > Jungle Focus > Durability Health (81) | Hunter Focus > Jungle Focus > Durability Health (80) |
| Vesper | Treasure Strength > Jungle Strength > Bruiser Health (190) | Hunter Strength > Jungle Health > Durability Health (84) | Monster Strength > Jungle Health > Durability Health (67) |
| Vendetta | Treasure Health > Jungle Strength > Bruiser Health (135) | Treasure Strength > Jungle Strength > Monster Strength (108) | Treasure Strength > Jungle Strength > Durability Strength (80) |
| Heart | Treasure Health > Jungle Focus > Bruiser Health (265) | Hunter Health > Jungle Focus > Bruiser Health (74) | Treasure Health (73) |
| Ryth | Jungle Health > Monster Health > Durability Health (78) | | |
| Prism | Monster Focus > Jungle Health > Bruiser Focus (20) | Monster Focus > Bruiser Focus > Bruiser Focus (19) | |
| Tavi | Treasure Health > Treasure Strength > Bruiser Strength (33) | Treasure Health > Capture Strength (32) | |
| Cassi | Power Focus > Durability Focus > Bruiser Health (48) | | |
| Issac | Treasure Strength > Power Strength > Home Health (33) | | |

Shard purchases over a game are dominated by Bruiser (stacked after the opener); Power second for some teams; new
families (Prospector, Capture, Hunter, Skirmish, Greed, Collectors) are rare except Hunter on some Vesper/Marcella/Heart
builds. Time at spawn is 4.5-5.7% of rounds (ours 2.3-2.8%): they return to shop and heal about twice as often.

## 9. Vision and consumables

- Wards: 77-231 placements a game per team (they re-place constantly). Of 190,329 placements: own half 47%, middle 47%,
  enemy half 6%; 60% within 4 tiles of a camp group, 23% within 4 tiles of an altar.
- Teleport crystals per game: Fish 2.7, Mite 3.9, Trzy 5.2, NEET 5.3, prism best girl 3.4, others 0-1.1.
- Altar locks per game: 3.3-8.3 for eight of ten teams (Fish 5.7, Mite 7.8, Claudus 8.3); 0 for two.

## 10. Fights

Replays, contact = enemy within 5 tiles:

| Champion | Contact | Approach / retreat / hold | Our side: ahead / even / behind | Approach when ahead / even / behind | HP when stepping away | Fighting under 35% HP |
|---|---|---|---|---|---|---|
| Heart | 21.1% | 41 / 35 / 24 | 52 / 36 / 12 | 44 / 39 / 33 | 74% | 9% |
| Vendetta | 16.4% | 46 / 32 / 21 | 48 / 37 / 15 | 50 / 44 / 38 | 68% | 12% |
| Vesper | 20.4% | 39 / 25 / 36 | 58 / 33 / 9 | 37 / 44 / 35 | 71% | 8% |
| Marcella | 19.2% | 43 / 28 / 29 | 53 / 35 / 13 | 48 / 40 / 29 | 71% | 8% |
| Ryth | 17.4% | 40 / 30 / 30 | 58 / 29 / 13 | 45 / 34 / 30 | 71% | 11% |
| Cassi / Issac | 23-27% | 22-32 / 11-26 / 42-67 | 85-90 / 8-12 / 2-3 | | 71-73% | 5-7% |
| Ours: Vesper | 14.8% | 36 / 19 / 45 | 45 / 38 / 17 | 42 / 32 / 26 | 64% | 9% |
| Ours: Tavi | 12.4% | 42 / 23 / 35 | 59 / 30 / 11 | 46 / 41 / 22 | 72% | 8% |
| Ours: Varg | 13.3% | 41 / 32 / 27 | 46 / 42 / 13 | 43 / 42 / 34 | 69% | 9% |
| Ours: Willow | 11.4% | 42 / 26 / 32 | 61 / 30 / 9 | 45 / 36 / 37 | 71% | 10% |

- They are in contact more (18.8% of champion-rounds vs our 12.7%) and are numerically ahead in 57% of contacts, behind
  in only ~10-13%. Our Vesper is behind in 17% of its contacts.
- They step away early (median HP 77% when moving away from an enemy; quartiles 53-95%), i.e. disengage long before
  the 30% line, and come back.
- Deaths by where/when (per game): own half late 1.92, middle late 1.68, own mid 0.91, middle mid 0.86; away deaths are
  rare (0.59 late). Ours are similar in shape but higher late (own 2.43, middle 2.42, away 1.11).
- First kill r173: early fighting is rare; fights start mid-game.
- Wins are decided by deaths: in top-10 wins deaths 5.6 vs 12.1, in losses 12.2 vs 5.4.

## 11. Map types

| Type | Games | Win | g300 vs opp | Deaths vs opp | Clears vs opp | Tributes x size | Wards | Rounds |
|---|---|---|---|---|---|---|---|---|
| Fight (<= 35) | 1,178 | 52% | 1,178 / 1,163 | 9.6 / 9.7 | 51 / 51 | 20.3 x 36 | 126 | 1,010 |
| Normal | 906 | 54% | 1,354 / 1,335 | 9.0 / 9.3 | 46 / 46 | 17.3 x 44 | 149 | 1,083 |
| Race (>= 70) | 385 | 53% | 1,055 / 1,051 | 5.5 / 5.8 | 53 / 52 | 25.6 x 33 | 148 | 1,107 |

On the maps we lose most, their gold at r300 vs ours: the_pack 1,715 vs 382, gold_rush 1,235 vs 496, treasure_box
2,076 vs 726, lanes 1,629 vs 971, broken_curve 1,487 vs 698, lost_world 639 vs 266, adgato_gemcombat1 261 vs 100.
Their draft is the same melee core on every map.

## 12. Closing gold and gem gaps

- Ahead by 150+ gold at r300: win 83% (978 games). Behind by 150+: win 22% (942 games).
- Comeback wins (204) vs failed comebacks (738), team vs opponent:
  - gold gained r300-600: 1,853 vs 1,729 | 1,087 vs 2,080;
  - gems collected at r300 / r600: 217 vs 207 / 579 vs 497 | 165 vs 249 / 351 vs 588;
  - deaths: 7.1 vs 10.8 (pre-r300 2.0 vs 1.2) | 13.4 vs 4.9;
  - tributes: 25.9 vs 17.6 | 12.5 vs 26.7;
  - clears away from home: 16.8 vs 12.8 | 10.0 vs 20.8; monoliths 0.33 vs 0.22 | 0.06 vs 0.34.
- In comebacks they keep collecting gems despite less gold, bank often, win fights on their side, and push into the
  enemy half once ahead in fights. A comeback that keeps dying stops farming away and loses.

## 13. Us vs them, side by side

| Measure | Top-10 | Us |
|---|---|---|
| Core draft | Marcella, Vesper, Vendetta, Heart | Vesper, Tavi, Willow, Varg (+ C&I) |
| Gold at r300 | 1,000-1,465 | ~940 |
| Clears early / mid | 14.8 / 14.9 | 9.3 / 9.6 |
| Opening camps | clusters and wolves on own half | big elk/golem groups |
| Share of time farming (early) | 26% | 17% |
| Time at spawn | ~5% | ~2.5% |
| Tribute size (median) | 21-26 | ~30-33 |
| Contact share / ahead in contact | 18.8% / 57% | 12.7% / 55% |
| HP when disengaging (median) | 77% | 73% |
| Earners | 2-3 strong (Marcella, Vesper, Vendetta) | 1 (Vesper), rest weak |
| Wards / teleports / locks | 77-231 / 0-5 / 0-8 | ~170 / ~1.6 / ~4 |

## 14. What this implies (interpretation)

1. **Draft for farming power, then fight with it.** Their core (Marcella, Vesper, Vendetta, Heart) is four champions
   who each farm 1.2-2.2k gold and fight; every body is a farmer. Our draft carries passengers (Willow 257-469 gold).
2. **Farm cheap camps first, everywhere on your own half, all game.** Opening with clusters and wolves gives a first
   clear at r19 and a steady ~5 clears per 100 rounds from the start; we spend the first 600 rounds slower.
3. **Spread to farm, gather to fight.** About half the time within 4 tiles of an ally, a third more than 8 away;
   contacts are taken when ahead (57%) and avoided when behind (~10%).
4. **Disengage early and come back.** Step away at ~75% HP, return to spawn ~5% of the time to heal and shop.
5. **Bank small and often.** Medians of 21-26 gems; the first tribute by r77. Marcella banks (2 gold per gem).
6. **Items: Treasure -> Jungle -> Bruiser/Durability, then stack Bruiser.** Health on melee, Strength on Vesper,
   Focus on Heart's Jungle.
7. **Vision near camps and altars on your own half; altar locks; teleports on some maps.**
8. **Comebacks come from fights and gems, not gold.**
