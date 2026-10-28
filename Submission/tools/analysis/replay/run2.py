import os as _os
SUB = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../..'))  # Submission/
import json,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
sp=json.load(open(SUB + '/tools/data/spawns.json'))
R={(r['team'],r['id']):r for r in json.load(open(SUB + '/tools/data/ladder/top10_rows.json')) if 'rounds' in r}
jobs=[]
for team,mid,m in json.load(open('pick.json')):
    r=R[(team,mid)]; jobs.append(('top',team,mid,m,r['side'],r['win'],f'top/{mid}.repl26a'))
for mid,m,side,win in json.load(open('ours_pick.json')): jobs.append(('ours','HighCortisol',mid,m,side,win,f'ours/{mid}.repl26a'))
def one(j):
    grp,team,mid,m,side,win,f=j
    if m not in sp: return None
    o=subprocess.run(['node','observe2.js',f,'0' if side=='a' else '1',json.dumps(sp[m]['SPAWN_A']),json.dumps(sp[m]['SPAWN_E'])],capture_output=True,text=True)
    try: d=json.loads(o.stdout.strip().splitlines()[-1]); d.update(grp=grp,team=team,id=mid,map=m,win=win); return d
    except Exception as e: return None
with ThreadPoolExecutor(8) as ex: res=[x for x in ex.map(one,jobs) if x]
json.dump(res,open('observe2.json','w')); print(len(res),'games')
