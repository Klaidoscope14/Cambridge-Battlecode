#!/usr/bin/env python3
"""Per-game stats for the top-10 teams' ranked matches (side = the top team). Writes rows.json incrementally."""
import os as _os
SUB = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../..'))  # Submission/
import json, os, sys, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, SUB + '/tools')
import panel

D = os.path.dirname(os.path.abspath(__file__))
SUB = SUB
geo = json.load(open(f'{SUB}/tools/data/geo.json'))
sp = json.load(open(f'{SUB}/tools/data/spawns.json'))
N = 'Ryth,Vesper,Vendetta,C&I,Stellar,Prism,Marcella,Willow,Ren,Varg,Tavi,Heart'.split(',')
L = json.load(open(f'{D}/lists.json'))
cen = lambda t: (sum(p[0] for p in t) / len(t), sum(p[1] for p in t) / len(t))
cheb = lambda a, b: max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def kind(g):
    if 'mono' in g['kinds']: return 'mono'
    if g['str'] <= 0: return 'cluster'
    if g['str'] <= 40: return 'small'
    return 'big'


def one(job):
    team, m = job
    me = [t for t in m['teams'] if t['name'] == team][0]
    op = [t for t in m['teams'] if t['name'] != team][0]
    r = dict(team=team, id=m['matchId'], map=m['map'], opp=op['name'], win=me['result'] == 'win', side=me['side'],
             draft=[N[int(c)] for c in me['draftPicks']], odraft=[N[int(c)] for c in op['draftPicks']])
    try:
        d = panel.summary(m['matchId'])
    except Exception:
        d = None
    if not d: return r
    T = 'team' + me['side'].upper(); O = 'teamB' if T == 'teamA' else 'teamA'
    ev = lambda k, t: [en for e in d['events'] if e['kind'] == k and e['owner'].get('team') == t for en in e['entries']]
    tl = lambda metric, t, rr: sum(panel.tl_at(c['runs'], rr) for c in d['championTimelines'] if c['metric'] == metric and c['owner']['team'] == t)
    r['rounds'] = d['match']['roundsCompleted']
    for nm, t in (('', T), ('o', O)):
        for rr in (100, 200, 300, 600):
            r[f'{nm}g{rr}'] = tl('earnedGold', t, rr); r[f'{nm}c{rr}'] = tl('collectedGems', t, rr)
        r[nm + 'deaths'] = len(ev('death', t)); r[nm + 'kills'] = len(ev('kill', t))
        r[nm + 'd300'] = sum(e['timestamp']['round'] < 300 for e in ev('death', t))
        r[nm + 'lost'] = sum(int(e['value']) for e in ev('gemLoss', t))
        subs = ev('gemSubmission', t)
        r[nm + 'tributes'] = len(subs); r[nm + 'sub'] = sum(int(e['value']) for e in subs)
        r[nm + 'wards'] = len(ev('wardPlacement', t))
        r[nm + 'cons'] = dict(collections.Counter(e['target'].get('name', '?') for e in ev('buyConsumable', t)))
        r[nm + 'shards'] = dict(collections.Counter(e['target']['name'].split(' ')[0] for e in ev('buyItem', t)))
        r[nm + 'shards400'] = dict(collections.Counter(e['target']['name'].split(' ')[0] for e in ev('buyItem', t) if e['timestamp']['round'] < 400))
        r[nm + 'first_buy'] = min([e['timestamp']['round'] for e in ev('buyItem', t)] or [9999])
        r[nm + 'altar_lock_hits'] = 0
        r[nm + 'gold_spread'] = sorted((float(c['metrics']['earnedGold']) for c in d['champions'] if c['team'] == t), reverse=True)
        r[nm + 'champs'] = [c['name'] for c in d['champions'] if c['team'] == t]
        # clears by kind / half / phase
        cl = collections.Counter()
        if r['map'] in geo and r['map'] in sp:
            G = geo[r['map']]['groups']; A = cen(sp[r['map']]['SPAWN_A']); E = cen(sp[r['map']]['SPAWN_E'])
            own = A if (t == 'teamA') else E; oth = E if t == 'teamA' else A
            for e in ev('campClear', t):
                i = e['target'].get('id', -1)
                if not (0 <= i < len(G)): continue
                g = G[i]; c = cen(g['tiles']); rd = e['timestamp']['round']
                cl[kind(g)] += 1
                cl['own' if cheb(c, own) < cheb(c, oth) else 'away'] += 1
                cl['<300' if rd < 300 else '<600' if rd < 600 else 'late'] += 1
        r[nm + 'clears'] = len(ev('campClear', t)); r[nm + 'clk'] = dict(cl)
    return r


jobs = [(team, m) for team, _ in L['teams'] for m in L['matches'][team]]
out = f'{D}/rows.json'
done = {}
if os.path.exists(out):
    for r in json.load(open(out)):
        if 'rounds' in r: done[(r['team'], r['id'])] = r
todo = [j for j in jobs if (j[0], j[1]['matchId']) not in done]
print(len(jobs), 'jobs,', len(todo), 'to do', flush=True)
rows = list(done.values())
with ThreadPoolExecutor(6) as ex:
    for k, r in enumerate(ex.map(one, todo)):
        rows.append(r)
        if k % 100 == 99:
            json.dump(rows, open(out, 'w')); print(k + 1, 'done', flush=True)
json.dump(rows, open(out, 'w'))
print('finished', sum('rounds' in r for r in rows), 'with summaries', flush=True)
