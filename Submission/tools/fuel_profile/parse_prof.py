import re,sys,glob
from collections import defaultdict
def parse(path):
    last={}  # kind -> (turnline dict, fn dict)
    cur=None
    for line in open(path):
        if line.startswith('PROFTURN'):
            kv=dict(re.findall(r'(\w+)=([\w.\-,]+)',line)); cur=kv['kind']; last[cur]=(kv,{})
        elif line.startswith('PROFFN') and cur:
            m=re.match(r'PROFFN (\S+) n=(\d+) sum=(\d+) avg=(\d+) max=(\d+) wrapped=(\d+)',line)
            if m: last[cur][1][m[1]]=(int(m[2]),int(m[3]),int(m[4]),int(m[5]),int(m[6]))
    return last
def summarize(path):
    L=parse(path)
    turns=sum(int(v[0]['turns']) for v in L.values()); tsum=sum(int(v[0]['avg'])*int(v[0]['turns']) for v in L.values())
    mx=max(int(v[0]['max']) for v in L.values()); o80=sum(int(v[0]['over80k']) for v in L.values()); o95=sum(int(v[0]['over95k']) for v in L.values()); wr=sum(int(v[0]['wrapped']) for v in L.values())
    fn=defaultdict(lambda:[0,0,0])
    for v in L.values():
        for k,(n,s,a,m,w) in v[1].items(): fn[k][0]+=n; fn[k][1]+=s; fn[k][2]=max(fn[k][2],m)
    return dict(turns=turns,avg=tsum/max(turns,1),max=mx,o80=o80,o95=o95,wrapped=wr,fn=fn,bodies=len(L),lastround=max(int(v[0]['r']) for v in L.values()))
if __name__=='__main__':
    for b in ('kprof','kprof0'):
        print('=====',b,'(GROUP_FIELDS on)' if b=='kprof' else '(GROUP_FIELDS off = v24 behaviour)')
        for m in ('01big_world','00lanes','00corners','00expanse','00split','01hooks'):
            S=summarize(f'{b}_{m}.txt')
            print(f"{m:12s} bodies {S['bodies']} to r{S['lastround']}: turns {S['turns']:5d} avg fuel/turn {S['avg']:6.0f} max {S['max']:6d} turns>80k {S['o80']:4d} ({S['o80']/S['turns']:.1%}) >95k {S['o95']:4d} wrapped(suspended) turns {S['wrapped']}")
