#!/usr/bin/env python3
"""Throughput metrics for local ab.py runs: python3 thr.py TAG [TAG...] (reads ~/.cache/kessoku_ab/TAG/*.json)."""
import json, glob, os, sys, statistics as st
def tl(runs, r):
    t = 0; v = 0.
    for x in runs:
        if t > r: break
        v = float(x['value']); t += x['duration']
    return v
for tag in sys.argv[1:]:
    rows = []
    for f in glob.glob(os.path.expanduser(f'~/.cache/kessoku_ab/{tag}/*.json')):
        d = json.load(open(f)); T = 'team' + f[-6]
        ev = lambda k: [en for e in d['events'] if e['kind'] == k and e['owner'].get('team') == T for en in e['entries']]
        g = lambda rr, m='earnedGold': sum(tl(c['runs'], rr) for c in d['championTimelines'] if c['metric'] == m and c['owner']['team'] == T)
        cl = [e['timestamp']['round'] for e in ev('campClear')]; sub = ev('gemSubmission')
        rows.append(dict(g300=g(300), g600=g(600), c300=g(300, 'collectedGems'), c600=g(600, 'collectedGems'), cl300=sum(x < 300 for x in cl),
                         cl600=sum(x < 600 for x in cl), first=min(cl or [999]), trib=len(sub), tsize=sum(int(e['value']) for e in sub) / max(1, len(sub)),
                         rounds=d['match']['roundsCompleted'], win=d['match']['outcome'] == T, deaths=len(ev('death')), odeaths=sum(1 for e in d['events'] if e['kind'] == 'death' and e['owner'].get('team') != T for _ in e['entries'])))
    if not rows: continue
    a = lambda k: st.mean(r[k] for r in rows)
    print(f"{tag:12s} n{len(rows)} win {sum(r['win'] for r in rows)} | gold@300 {a('g300'):5.0f} @600 {a('g600'):5.0f} | gems@300 {a('c300'):4.0f} @600 {a('c600'):4.0f} | clears<300 {a('cl300'):4.1f} <600 {a('cl600'):4.1f} first r{st.median(r['first'] for r in rows):.0f} | tributes {a('trib'):4.1f} x {a('tsize'):3.0f} | deaths {a('deaths'):.1f}/{a('odeaths'):.1f} rounds {a('rounds'):.0f}")
