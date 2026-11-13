"""Aggregate last-closed attention counts only; never wallet identities or contents."""
import json,os,tempfile
from pathlib import Path
PAGES=('authorise','burn','peers','services','message','synchronisation','wallets')
def checked(value):
    return {page:(value.get(page,0) if isinstance(value,dict) and type(value.get(page,0)) is int and 0<=value.get(page,0)<=100000 else 0) for page in PAGES}
def counts(view,peer_pending=0):
    transfer=view.get('transfer',{});recovery=transfer.get('recovery',{});burn=view.get('burn',{});archives=view.get('archives',{})
    result=checked({});result['authorise']=len(view.get('pending',[]))+len(view.get('setups',[]))
    result['synchronisation']=int(transfer.get('pending_count') or 0)+int(bool(recovery.get('can_refresh') and not recovery.get('running') and recovery.get('status') not in (None,'Synchronised')))
    result['burn']=len(archives.get('staged',[]))+len(archives.get('loaded',[]))+int(bool(burn.get('id') and burn.get('phase') not in ('burning','verifying','complete','verified')))
    result['peers']=peer_pending;result['services']=int(bool(view.get('cleanup_recovery')))
    return checked(result)
def location():
    from configuration import Config
    return Config().root/'sidebar-counts.json'
def save(value):
    path=location();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd,name=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(checked(value),f)
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)
def load():
    try:return checked(json.loads(location().read_text()))
    except (OSError,ValueError,TypeError):return checked({})
