import json, subprocess, os
S=os.path.dirname(os.path.abspath(__file__))
REPO='/home/user/ValuCast'
DAYS={'2026-07-23':'5e8959d','2026-07-24':'1d63585','2026-07-25':'d4ae26f',
      '2026-07-26':'b8cd8a9','2026-07-27':'d83a9a7','2026-07-28':'3e044b1'}
def run(cmd,cwd=None):
    r=subprocess.run(cmd,shell=True,cwd=cwd,capture_output=True,text=True)
    if r.returncode!=0: raise SystemExit(f'FAIL: {cmd}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}')
    return r.stdout
os.makedirs(f'{S}/boards032',exist_ok=True)
WT=f'{S}/wt032b'
run(f'git -C {REPO} worktree add --detach {WT} 3c847df')
try:
    run(f'git -C {WT} apply {S}/patch032.diff')
    for day,sha in DAYS.items():
        run(f'git -C {WT} checkout {sha} -- data')
        run('python scripts/build_prospect_rank_v1.py',cwd=WT)
        run(f'cp {WT}/data/models/valucast_prospect_rank_v1.json {S}/boards032/{day}.json')
        print('built',day,flush=True)
finally:
    run(f'git -C {REPO} worktree remove --force {WT}')
WT2=f'{S}/wt032h'
run(f'git -C {REPO} fetch origin master')
run(f'git -C {REPO} worktree add --detach {WT2} HEAD')
try:
    # apply the uncommitted 0.3.2 edits onto HEAD code
    run(f'git -C {WT2} apply {S}/patch032.diff')
    run(f'git -C {WT2} checkout origin/master -- data')
    run('python scripts/build_prospect_rank_v1.py',cwd=WT2)
    run(f'cp {WT2}/data/models/valucast_prospect_rank_v1.json {S}/boards032/current.json')
    served=run(f'git -C {REPO} show origin/master:data/models/valucast_prospect_rank_v1.json')
    open(f'{S}/boards032/served-current.json','w').write(served)
    print('built current preview',flush=True)
finally:
    run(f'git -C {REPO} worktree remove --force {WT2}')
print('OK')
