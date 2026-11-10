"""Consume the matching Server's exported discovery fixture in an isolated Store."""
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from approval_store import Store
from sync_queue import apply_snapshot
from sync_offers import apply

payload=json.loads(Path(sys.argv[1]).read_text())
with tempfile.TemporaryDirectory() as folder:
    store=Store(folder)
    for p in payload['proposals']:
        if p['kind']=='wallet_sync_queue':apply_snapshot(store,p['revision'],p['requests'],session='isolated-server7-fixture')
        elif p['kind']=='wallet_sync_offers':apply(store,p,'isolated-server7-fixture')
        else:raise AssertionError('Unexpected discovery fixture kind')
    saved=store.read()
    assert len(saved['pending'])==len(saved['sync_offers'])==1
    p=next(iter(saved['pending'].values()))['proposal']
    assert p['transfer_version']==3 and p['source_has_private_keys'] is False
    assert not {'manifest','records','coverage','history_sync','summary'}&p.keys()
    assert not saved.get('local_retirements') and not saved['completed']
print('Server 7 discovery accepted by Agent 78: existing direct protocol, no historical payload, local extinction consent or operation outcome supplied by Server.')
