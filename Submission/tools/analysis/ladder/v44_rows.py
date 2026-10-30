#!/usr/bin/env python3
"""Per-game rows for one version's ranked games: python3 v44_rows.py [VER] (default v44) -> ~/.cache/kessoku_ladder/VER/rows.json
VER/list.json holds that version's ranked match list (cambc matches list entries); summaries come from ~/.cache/kessoku_ladder."""
import os as _os
SUB = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../..'))  # Submission/
import json, os, collections, sys
VER = sys.argv[1] if len(sys.argv) > 1 else 'v44'
D = os.path.expanduser('~/.cache/kessoku_ladder')
SP = json.load(open(SUB + '/tools/data/spawns.json'))
v = json.load(open(f'{D}/{VER}/list.json'))
def tl(runs, r):
    t = 0; val = 0.
    for x in runs:
        if t > r: break
        val = float(x['value']); t += x['duration']
    return val
rows = []
for m in v:
    f = f"{D}/match-{m['matchId']}.json"
    if not os.path.exists(f): continue
    j = json.load(open(f))
    us = [t for t in m['teams'] if t['name'] == 'HighCortisol'][0]; them = [t for t in m['teams'] if t['name'] != 'HighCortisol'][0]
    T = 'team' + us['side'].upper(); O = 'teamB' if T == 'teamA' else 'teamA'
    sp = SP.get(m['map'])
    own = [tuple(p) for p in (sp['SPAWN_A'] if us['side'] == 'a' else sp['SPAWN_E'])] if sp else None
    opp = [tuple(p) for p in (sp['SPAWN_E'] if us['side'] == 'a' else sp['SPAWN_A'])] if sp else None
    def half(x, y):
        if not own: return '?'
        a = min(max(abs(x - p[0]), abs(y - p[1])) for p in own); b = min(max(abs(x - p[0]), abs(y - p[1])) for p in opp)
        return 'own' if a < 0.8 * b else 'away' if b < 0.8 * a else 'mid'
    names = {c['id']: (c['name'], c['team']) for c in j['roster']['champions']}
    ev = lambda k, team: [(e['owner'], x) for e in j['events'] if e['kind'] == k and e['owner'].get('team') == team for x in e['entries']]
    deaths = ev('death', T); odeaths = ev('death', O)
    g = lambda team, metric, r: sum(tl(c['runs'], r) for c in j['championTimelines'] if c['metric'] == metric and c['owner']['team'] == team)
    clears = ev('campClear', T); oclears = ev('campClear', O)
    sub = {t['team']: int(t['submittedGems']) for t in j['teams']}
    rows.append(dict(
        id=m['matchId'], t=m['createdAt'], map=m['map'], opp=them['name'], side=us['side'], win=us['result'] == 'win',
        end=m.get('endReason'), rounds=j['match'].get('roundsCompleted') or max([x['timestamp']['round'] for _, x in deaths + odeaths + clears] or [0]),
        ours=sorted({names[c['id']][0] for c in j['roster']['champions'] if c['team'] == T}),
        theirs=sorted({names[c['id']][0] for c in j['roster']['champions'] if c['team'] == O}),
        deaths=len(deaths), odeaths=len(odeaths),
        d_ctx=dict(collections.Counter(x['context'] for _, x in deaths)),
        d_half=dict(collections.Counter(half(x['x'], x['y']) for _, x in deaths)),
        d_early=sum(x['timestamp']['round'] < 300 for _, x in deaths), od_early=sum(x['timestamp']['round'] < 300 for _, x in odeaths),
        d_who=dict(collections.Counter(o['name'] for o, _ in deaths)),
        killers=dict(collections.Counter(x['target']['name'] for _, x in deaths if isinstance(x.get('target'), dict) and x['target'].get('kind') == 'champion')),
        g300=g(T, 'earnedGold', 300), og300=g(O, 'earnedGold', 300), g600=g(T, 'earnedGold', 600), og600=g(O, 'earnedGold', 600),
        c300=g(T, 'collectedGems', 300), oc300=g(O, 'collectedGems', 300),
        cl300=sum(x['timestamp']['round'] < 300 for _, x in clears), ocl300=sum(x['timestamp']['round'] < 300 for _, x in oclears),
        clears=len(clears), oclears=len(oclears),
        sub=sub.get(T, 0), osub=sub.get(O, 0),
        lost=sum(int(x['value']) for _, x in ev('gemLoss', T)), olost=sum(int(x['value']) for _, x in ev('gemLoss', O)),
        trib=len(ev('gemSubmission', T)), otrib=len(ev('gemSubmission', O)),
        wards=len(ev('wardPlacement', T)), owards=len(ev('wardPlacement', O)),
    ))
json.dump(rows, open(f'{D}/{VER}/rows.json', 'w'))
print(len(rows), 'rows')
