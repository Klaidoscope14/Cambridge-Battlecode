#!/usr/bin/env python3
"""Compare bot versions on the ladder: win rate, deaths, traded deaths, deaths on our half, capture theft.

usage (from Submission/, after `cambc login`):
  python3 tools/ladder_compare.py NAME=START_UTC [NAME=START_UTC ...]
  e.g. python3 tools/ladder_compare.py v28=2026-10-22T19:30 v29=2026-10-24T18:10 v30=2026-10-25T03:00
Each version owns the ranked games created from its START until the next version's START. Summaries are
cached in ~/.cache/kessoku_ladder (4 download threads with backoff). Spawns come from tools/data/spawns.json
(made with bots/zgeo; side A = SPAWN_A).
"""
import collections, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser('~/.cache/kessoku_ladder'); os.makedirs(CACHE, exist_ok=True)
SPAWNS = json.load(open(os.path.join(HERE, 'data', 'spawns.json')))
eras = sorted((v.split('=', 1)[1], v.split('=', 1)[0]) for v in sys.argv[1:])
if not eras: sys.exit(__doc__)

def cambc(*a):
    for k in range(6):  # the API rate-limits: retry with backoff
        out = subprocess.run(['cambc', *a], capture_output=True, text=True).stdout
        try:
            return json.loads(out[out.find('{'):out.rfind('}') + 1])
        except ValueError:
            time.sleep(5 + 5 * k)
    raise SystemExit('cambc ' + ' '.join(a) + ' failed (logged in?)')

matches, cur = [], None
while True:
    d = cambc('matches', 'list', '--team', 'me', '--kind', 'ranked', '--limit', '100', '--json', *(['--cursor', cur] if cur else []))
    matches += d['matches']; cur = d.get('nextCursor')
    if not cur or d['matches'][-1]['createdAt'] < eras[0][0]: break
rows = []
for m in matches:
    if m['createdAt'] < eras[0][0]: continue
    us = next(t for t in m['teams'] if t['name'] == 'HighCortisol')
    if us['result'] not in ('win', 'loss'): continue
    era = [n for s, n in eras if m['createdAt'] >= s][-1]
    rows.append(dict(id=m['matchId'], era=era, map=m['map'], win=us['result'] == 'win', side=us['side']))

def fetch(i):
    j = f'{CACHE}/match-{i}.json'; c = f'{CACHE}/match-{i}.camstat'
    for k in range(8):
        if os.path.exists(j) and os.path.getsize(j) > 1000: return
        if not os.path.exists(c): subprocess.run(['cambc', 'matches', 'summary', i], cwd=CACHE, capture_output=True)
        if os.path.exists(c): subprocess.run(['cambc', 'summary', c, '-o', j], capture_output=True); continue
        time.sleep(4 + 4 * k)
with ThreadPoolExecutor(4) as ex: list(ex.map(fetch, [r['id'] for r in rows]))

cheb = lambda a, b: max(abs(a[0] - b[0]), abs(a[1] - b[1]))
near = lambda p, tiles: min(cheb(p, t) for t in tiles)
stats = {n: collections.Counter() for _, n in eras}; maps = {n: collections.defaultdict(lambda: [0, 0]) for _, n in eras}
for r in rows:
    try: d = json.load(open(f'{CACHE}/match-{r["id"]}.json'))
    except Exception: continue
    A = stats[r['era']]; us = 'team' + r['side'].upper()
    g = SPAWNS.get(r['map'], {}); sa, se = (g.get('SPAWN_A'), g.get('SPAWN_E')) if r['side'] == 'a' else (g.get('SPAWN_E'), g.get('SPAWN_A'))
    A['games'] += 1; A['wins'] += r['win']; maps[r['era']][r['map']][0] += r['win']; maps[r['era']][r['map']][1] += 1
    ours, theirs, col = [], [], collections.defaultdict(list)
    for e in d['events']:
        for en in e['entries']:
            if e['kind'] == 'kill' and en['target'].get('kind') == 'champion':
                (ours if en['target'].get('team') == us else theirs).append((en['timestamp']['round'], (en['x'], en['y'])))
            if e['kind'] == 'gemCollection' and isinstance(en.get('target'), dict):
                col[en['target']['id']].append((en['timestamp']['round'], e['owner'].get('team'), int(en['value'])))
    A['deaths'] += len(ours); A['loss_deaths' if not r['win'] else 'win_deaths'] += len(ours)
    for t, p in ours:
        A['traded'] += any(abs(u - t) <= 6 for u, _ in theirs)
        if sa and se: A['ours_on_our_half'] += near(p, sa) < near(p, se)
    for t, p in theirs:
        if sa and se: A['theirs_on_our_half'] += near(p, sa) < near(p, se)
    for e in d['events']:
        if e['kind'] != 'campClear': continue
        for en in e['entries']:
            if not isinstance(en.get('target'), dict): continue
            rd = en['timestamp']['round']; team = e['owner'].get('team')
            after = sorted(x for x in col[en['target']['id']] if rd <= x[0] <= rd + 40)
            if after and team not in {x[1] for x in after if x[0] == after[0][0]}:
                A['stolen' if team == us else 'stole'] += sum(x[2] for x in after if x[0] == after[0][0])
base = eras[0][1]
for _, n in eras:
    A = stats[n]; g = max(A['games'], 1); L = max(A['games'] - A['wins'], 1); W = max(A['wins'], 1)
    exp = ''
    if n != base:
        mix = maps[n]; b = maps[base]
        e = sum(c[1] * b[m][0] / b[m][1] for m, c in mix.items() if b[m][1]) / max(sum(c[1] for m, c in mix.items() if b[m][1]), 1)
        exp = f" ({base} on this map mix: {e:.0%})"
    print(f"{n}: {A['games']} games, win {A['wins']/g:.0%}{exp} | deaths/loss {A['loss_deaths']/L:.1f} deaths/win {A['win_deaths']/W:.1f} "
          f"traded {A['traded']/max(A['deaths'],1):.0%} | our deaths on our half {A['ours_on_our_half']/g:.1f}/game, theirs {A['theirs_on_our_half']/g:.1f} "
          f"| stolen from us {A['stolen']/g:.1f} gems/game, we stole {A['stole']/g:.1f}")
