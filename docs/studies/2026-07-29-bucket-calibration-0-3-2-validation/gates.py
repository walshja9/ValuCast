import json, os, subprocess
S=os.path.dirname(os.path.abspath(__file__))
E31=os.path.abspath(os.path.join(S,'..','eval031'))
DAYS=['2026-07-%02d'%d for d in range(23,29)]
def board(p): return json.load(open(p))['board']
def key(r): return (str(r['mlbam_id']), r.get('role'))
def floor_flag(r):
    comp=(r.get('components') or {}).get('bucket_calibration') or {}
    return any(x.get('continuity_floor_applied') is True for x in comp.get('rules') or [] if isinstance(x,dict))

g1_viol=[]; g2_viol=[]; g2_total=0
for day in DAYS:
    C={key(r):r for r in board(f'{S}/boards032/{day}.json')}
    A={key(r):r for r in board(f'{E31}/boards/armA/{day}.json')}
    B={key(r):r for r in board(f'{E31}/boards/armB/{day}.json')}
    for k,rc in C.items():
        if floor_flag(rc):
            g2_total+=1
            rb=B.get(k)
            if rb is None or round(rc.get('score') or 0,2)!=round(rb.get('score') or 0,2) or not floor_flag(rb):
                g2_viol.append((day,k,rc.get('name'),rc.get('score'),rb and rb.get('score')))
        else:
            ra=A.get(k)
            if ra is None or round(rc.get('score') or 0,2)!=round(ra.get('score') or 0,2):
                g1_viol.append((day,k,rc.get('name'),rc.get('score'),ra and ra.get('score')))
    # also confirm no floor row in C is missing vs B's floor set
    bfloor={k for k,r in B.items() if floor_flag(r)}
    cfloor={k for k,r in C.items() if floor_flag(r)}
    if bfloor!=cfloor:
        g2_viol.append((day,'floor-set-mismatch',sorted(bfloor^cfloor)[:10],None,None))
print('GATE1 non-floor exact-match violations:',len(g1_viol)); [print('  ',v) for v in g1_viol[:10]]
print('GATE2 floor rows checked:',g2_total,'violations:',len(g2_viol)); [print('  ',v) for v in g2_viol[:10]]

# GATE 3: restored veto over 0.3.2 day pairs
import sys; sys.path.insert(0,'/home/user/ValuCast')
from quality.valucast_governor import _prospect_transition_continuity
prior=json.load(open(f'{E31}/boards/prior-2026-07-22.json'))
seq=[prior]+[json.load(open(f'{S}/boards032/{d}.json')) for d in DAYS]
for i in range(1,len(seq)):
    res=_prospect_transition_continuity(seq[i],seq[i-1])
    print(f'GATE3 pair {i}: {res["status"]} incidents={res["metrics"].get("incident_count")}')

# GATE 4: current-board preview vs served
C=board(f'{S}/boards032/current.json'); Sv=board(f'{S}/boards032/served-current.json')
ci={key(r):r for r in C}; si={key(r):r for r in Sv}
changes=[]
for k,rc in ci.items():
    rs=si.get(k)
    if rs is None: continue
    d=(rc.get('score') or 0)-(rs.get('score') or 0)
    if abs(d)>=0.01:
        changes.append((abs(d),k,rc.get('name'),rc.get('role'),rc.get('level'),
                        round(rs.get('score') or 0,2),round(rc.get('score') or 0,2),round(d,2),
                        rs.get('rank'),rc.get('rank'),floor_flag(rc)))
changes.sort(reverse=True)
t100=[c for c in changes if (c[8]<=100)!=(c[9]<=100)]
import statistics
mags=[c[0] for c in changes]
print(f'GATE4 preview: changed={len(changes)} median|d|={statistics.median(mags):.2f}' if mags else 'GATE4 preview: changed=0')
print('  top-100 boundary crossings:',len(t100))
for c in t100: print('   ',c[2],c[3],'served rank',c[8],'-> 0.3.2 rank',c[9],'delta',c[7])
print('  20 largest moves:')
for c in changes[:20]: print('   ',c[2],c[3],c[4],'score',c[5],'->',c[6],'rank',c[8],'->',c[9],'floor' if c[10] else '')
import csv
with open(f'{S}/preview_changes.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['mlbam_id','role','name','level','score_served','score_032','delta','rank_served','rank_032','floor'])
    for c in changes: w.writerow([c[1][0],c[3],c[2],c[4],c[5],c[6],c[7],c[8],c[9],c[10]])
print('preview csv written')
