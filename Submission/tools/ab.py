#!/usr/bin/env python3
"""Parallel A/B runner: both sides of every map via `cambc run-batch`, one line per game + a summary.

usage (from Submission/): python3 tools/ab.py TAG BOT OPP [map ...]
  - no maps: every ladder-pool map in maps/ (the 00*/01* files, 40 on 2026-10-24)
  - results go to $AB_OUT/TAG (default: $TMPDIR/kessoku_ab/TAG); finished games are reused
    on a rerun with the same TAG, so delete that folder when a bot changes
  - JOBS=8 sets parallel runner processes; games use --release, as on the platform
Use the frozen live version as the mirror opponent, e.g.:
  cambc build v29 && python3 tools/ab.py mytest kessoku v29
A mirror at parity wins half the games (matches are deterministic).
"""
import json, os, subprocess, sys, tempfile

P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Submission/
POOL = set(open(os.path.join(P, 'tools', 'data', 'pool.txt')).read().split())  # the ladder map pool (cambc maps list)
tag, bot, opp, maps = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
if not maps:
    maps = sorted(f[:-7] for f in os.listdir(f'{P}/maps') if f.endswith('.map26a') and f[:-7] in POOL)
jobs = int(os.environ.get('JOBS', '8'))
D = os.path.join(os.environ.get('AB_OUT', os.path.join(tempfile.gettempdir(), 'kessoku_ab')), tag)
os.makedirs(D, exist_ok=True)

rows = []
with open(f'{D}/manifest.txt', 'w') as f:
    for m in maps:
        for side in 'AB':
            a, b = (bot, opp) if side == 'A' else (opp, bot)
            k = f'{m}_{side}'
            rows.append((m, side, k))
            if os.path.exists(f'{D}/{k}.json'):
                continue
            f.write(f'{P}/bots/{a} {P}/bots/{b} {P}/maps/{m}.map26a {D}/{k}.repl26a --statistics {D}/{k}.json --json\n')
subprocess.run(['cambc', 'run-batch', '--jobs', str(jobs), '--release', f'{D}/manifest.txt'], cwd=P, capture_output=True)

W = G = 0
tot = dict(dead=0, odead=0, gold=0, sub=0, osub=0, faults=0, rsum=0)
for m, side, k in rows:
    try:
        d = json.load(open(f'{D}/{k}.json'))
    except Exception:
        print(f'{m:22s} {side} MISSING')
        continue
    us = 'team' + side
    them = 'teamB' if side == 'A' else 'teamA'
    sub = {t['team']: int(t['submittedGems']) for t in d['teams']}
    met = lambda t, x: sum(float(c['metrics'][x]) for c in d['champions'] if c['team'] == t)
    win = d['match']['outcome'] == us
    W += win
    G += 1
    r = d['match']['roundsCompleted']
    fl = d['diagnostics']['botFaults'][us]
    tot['dead'] += met(us, 'deaths'); tot['odead'] += met(them, 'deaths'); tot['gold'] += met(us, 'earnedGold')
    tot['sub'] += sub[us]; tot['osub'] += sub[them]; tot['faults'] += fl
    if win:
        tot['rsum'] += r
    print(f"{m:22s} {side} {'WIN ' if win else 'loss'} r{r:4d} sub {sub[us]:4d}-{sub[them]:4d} "
          f"deaths {met(us, 'deaths'):3.0f}-{met(them, 'deaths'):3.0f} "
          f"gold {met(us, 'earnedGold'):6.0f}-{met(them, 'earnedGold'):6.0f} faults {fl}")
print(f"SUMMARY {tag} {bot} vs {opp}: wins={W}/{G} avg_win_round={tot['rsum'] // max(W, 1)} "
      f"sub={tot['sub']:.0f}-{tot['osub']:.0f} deaths={tot['dead']:.0f}-{tot['odead']:.0f} "
      f"gold={tot['gold']:.0f} faults={tot['faults']}")
