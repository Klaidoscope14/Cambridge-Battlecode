# usage: python3 equiv.py BASE_TAG OPT_TAG   (tags under $TMPDIR/kessoku_ab produced by tools/ab.py)
import json,os,glob,sys
T=os.environ.get('TMPDIR','/tmp')+'kessoku_ab/'
def load(tag):
    out={}
    for f in glob.glob(T+tag+'/*.json'):
        k=os.path.basename(f)[:-5]
        if k=='manifest': continue
        d=json.load(open(f)); us='team'+k[-1]
        sub={t['team']:int(t['submittedGems']) for t in d['teams']}
        fz=lambda mine:sum(len(e['entries']) for e in d['events'] if e['kind']=='fuelExhausted' and (e['owner']['team']==us)==mine)
        out[k]=dict(sig=(d['match']['roundsCompleted'],sub['teamA'],sub['teamB'],sum(float(c['metrics']['deaths']) for c in d['champions']),sum(float(c['metrics']['earnedGold']) for c in d['champions']),d['match']['outcome']),fuel=fz(True),fuel_opp=fz(False))
    return out
a=load(sys.argv[1]); b=load(sys.argv[2])
ident=[k for k in a if a[k]['sig']==b[k]['sig']]
free=[k for k in a if a[k]['fuel']==0 and b[k]['fuel']==0 and a[k]['fuel_opp']==0]
print(f"games {len(a)}; identical signature {len(ident)}; fuel-unconstrained in both builds {len(free)}, identical among them {sum(1 for k in free if k in ident)}")
print('fuel-exhausted events: base',sum(v['fuel'] for v in a.values()),' opt',sum(v['fuel'] for v in b.values()))
for k in free:
    if k not in ident: print('  UNEXPECTED DIFF (no fuel pressure):',k,a[k]['sig'],b[k]['sig'])
