"""Run with Server Build 6 on PYTHONPATH; invented data, two programs/processes."""
import json,subprocess,sys
from pathlib import Path
sys.path[:]=[p for p in sys.path if Path(p).resolve()!=Path(__file__).resolve().parent]
from test_wallet_server6 import Offers
from sync_permissions import policy_id
f=Offers('test_ready_offer_links_to_exact_executable_transfer_and_stable_revision');f.setUp()
try:
 first=f.exchange(f.f.a)
 f.hub.permissions.live[f.f.b['node_id']]['record']['policies']=[policy_id(f.f.wallet['raw'])]
 denied=f.exchange(f.f.a)
 f.hub.permissions.live[f.f.b['node_id']]['record']['policies']=[]
 enabled=f.exchange(f.f.a)
 code='''import sys,json,tempfile
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from approval_store import Store
from sync_offers import apply
from sync_queue import apply_snapshot,rows
from sync_table import state,choose
replies=json.loads(sys.stdin.read())
with tempfile.TemporaryDirectory() as folder:
 s=Store(folder);counts=[]
 for i,reply in enumerate(replies):
  o=next(p for p in reply['proposals'] if p['kind']=='wallet_sync_offers')
  if i==0:
   q=next(p for p in reply['proposals'] if p['kind']=='wallet_sync_queue');apply_snapshot(s,q['revision'],q['requests'])
  # Deliberately retain the old executable request to test independent withdrawal.
  apply(s,o,'server-session')
  with patch('sync_table.direct_ready',return_value=True):
   counts.append(state(s,rows(s))['pending_count'])
   if i==0:choose(s,rows(s)[0]['id'],True,False)
   if i==1:
    assert not any(w['send'] for w in state(s,rows(s))['wallets'])
    assert not any(c['selected'] for c in s.read()['sync_choices'].values())
 assert counts==[1,0,1],counts
 assert not s.read().get('sync_batch') and not s.read()['completed']
 print('PASS real Server 6 snapshots + Agent 72: sender counts 1 -> 0 -> 1, stale executable row blocked, re-enable restores visibility without selected transfer or wallet operation.')
'''
 agent=str(Path(__file__).resolve().parents[1]/'src');r=subprocess.run([sys.executable,'-c',code,agent],input=json.dumps([first,denied,enabled]),capture_output=True,text=True);print(r.stdout,end='');print(r.stderr,end='',file=sys.stderr);raise SystemExit(r.returncode)
finally:f.doCleanups()
