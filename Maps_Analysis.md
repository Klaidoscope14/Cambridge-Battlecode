# CAMBC 2026 — Map Pool Analysis (9 maps)

Data source: binary `.map26a` header decode (size/team/symmetry — 100% reliable) +
the official visualiser's WASM engine (exact walls/holes/bushes/altars via the
in-memory chunked bitboards). Camp/monster positions are NOT included here — they
proved unreliable to extract headlessly, but your bot reads them at runtime during
the full-vision draft via the API.

## File format (`.map26a`), reverse-engineered
- Bytes `0x00–0x47` (72 B): fixed preamble — magic `w62pam` + a 12-colour editor palette (identical in every file).
- `0x48`: symmetry code — **0 = HORIZONTAL (left/right mirror), 1 = VERTICAL (top/bottom mirror, inferred), 2 = ROTATIONAL180**.
- `0x49`: champions per team (3–5).
- `0x4A–0x4B`: width (u16 LE). `0x4C–0x4D`: height (u16 LE).
- `0x4E…`: RLE terrain grid (tile types incl. wall/hole/bush/altar), then a trailing `(x,y,kind)` camp-record section.
- Engine stores terrain as 128-byte-per-board chunked bitboards (8×8 tiles per 64-bit word): `wallBuffer`, `holeBuffer`, `bushBuffer`, `altarBuffer`.

## Comparison table

| UUID prefix | Size | Tiles | Team | Symmetry | Walls | Holes | Bushes | Altars | Character |
|---|---|---|---|---|---|---|---|---|---|
| 81824dd7 | 31×31 | 961 | 3 | ROTATIONAL180 | 0 | 0 | 62 | 6 | Small, fully open, light bush cover |
| bb12893c | 30×30 | 900 | 5 | ROTATIONAL180 | — | — | — | — | Smallest; terrain not captured (5 champs on a tiny map = crowded) |
| 49a6f0b9 | 40×40 | 1600 | 4 | ROTATIONAL180 | 76 | 16 | 38 | 4 | Medium, moderately walled |
| 3bf50c50 | 41×41 | 1681 | 3 | VERTICAL(1) | 84 | 60 | 222 | 2 | Very bushy + walled (maze-like); only 2 altars |
| 25d81311 | 50×50 | 2500 | 4 | ROTATIONAL180 | 214 | 0 | 142 | 2 | Heavily walled (8.6%); only 2 altars |
| 3991a8b3 | 50×50 | 2500 | 5 | ROTATIONAL180 | 98 | 0 | 66 | 6 | Medium clutter; altars along the diagonal |
| 8b48383d | 71×71 | 5041 | 5 | HORIZONTAL | 44 | 84 | 60 | 5 | Large, very open (0.9% walls); altars 4 corners + center |
| 4705f2c8 | 80×80 | 6400 | 3 | ROTATIONAL180 | 224 | 16 | 0 | 10 | Large, walled, NO bushes (open sightlines); only 3 champs |
| df106d8d | 90×30 | 2700 | 5 | HORIZONTAL | 0 | 76 | 144 | 18 | Wide corridor; no walls, lots of bushes, 18 altars |

## Exact altar positions (tributing points)
- **81824dd7** (6): (2,6)(28,6)(2,15)(28,15)(2,24)(28,24) — two vertical columns at the left/right edges.
- **49a6f0b9** (4): (36,12)(3,27) & (19,16)(20,23) — two rotational pairs.
- **3bf50c50** (2): (27,20)(39,20) — both on the centre row, right side.
- **25d81311** (2): (15,16)(34,33) — one rotational pair, near-centre.
- **3991a8b3** (6): (4,1)(45,48)(12,10)(37,39)(19,19)(30,30) — three pairs strung along the main diagonal.
- **8b48383d** (5): (1,1)(69,1)(1,69)(69,69)(35,34) — four corners + dead centre.
- **4705f2c8** (10): (14,4)(65,75)(39,16)(40,63)(13,26)(66,53)(38,34)(41,45)(67,32)(12,47) — five rotational pairs spread across the board.
- **df106d8d** (18): rows at y=4/13/25, x≈{11-13,20,29} mirrored to x≈{60,69,76-78} — six altars per band, both halves.

## Spawn locations (confirmed)
- **81824dd7** (team 3): corners (0,0) ↔ (30,30) — rotational.
- **df106d8d** (team 5): 3×3 blocks at x2–4 / y12–14 (left) ↔ x85–87 / y12–14 (right) — horizontal mirror, mid-height.
- Other maps: spawns sit symmetrically per the map's symmetry; the bot reads exact tiles at draft time.

## Notes
- Every map is symmetric (fair). ROTATIONAL180 dominates (6/9); HORIZONTAL on the two "wide/large open" maps; one VERTICAL.
- Altar scarcity varies hugely: 2 altars (25d81311, 3bf50c50) → tribute chokepoints worth contesting/locking, vs 18 (df106d8d) → tribute is easy, racing/fighting matters more.
- Bush density = vision/ambush game (3bf50c50, df106d8d, 25d81311 high; 4705f2c8 none → open sightlines).
- Team size is per-map: 3 on 81824dd7/3bf50c50/4705f2c8; 4 on 49a6f0b9/25d81311; 5 on bb12893c/3991a8b3/8b48383d/df106d8d.
