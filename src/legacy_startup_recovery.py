"""One guarded recovery of unattempted legacy retirement/history metadata.

Inspection runs inside an existing protected viewer child. The ordinary caller
sees only nonce/PID-bound success flags, never wallet state or secret material.
"""
import json,os,secrets,time
from pathlib import Path
from protected_memory import root,enforce
from peer_protocol import hexid
from approval_store import Store,digest
from secure_bridge import call
from worker_upgrade import identity
REQUEST='legacy-startup-recovery-request.json'
RESULT='legacy-startup-recovery-result.json'

def dismiss(store,core,key,status,deadline=None):
    from wallet_ops import rpc
    from build8_policy import descriptors
    from secure_worker import delivery_pending
    if status.get('status_pending') or status.get('setups') or status.get('burn',{}).get('id'):raise ValueError('Other protected work exists.')
    archives=status.get('archives',{})
    if archives.get('reading') or archives.get('loaded') or archives.get('staged'):raise ValueError('Archive work is present.')
    transfer=status.get('transfer',{});recovery=transfer.get('recovery',{})
    if transfer.get('id') or transfer.get('sending') or transfer.get('ready') or recovery.get('running') is not False or recovery.get('job',{}).get('state')!='error':raise ValueError('Recovery is active or its outcome needs another review.')
    saved=store.read();pending=saved.get('pending',{});jobs=saved.get('history_jobs',{})
    if set(pending)!={key} or pending[key]['state']!='pending' or pending[key]['proposal']['kind']!='wallet_retire' or not jobs or saved.get('active_transfer') or saved.get('sync_batch'):raise ValueError('The exact legacy request has changed.')
    if delivery_pending(saved) or saved.get('recovery',{}).get('state')!='error':raise ValueError('A delivery or recovery needs attention.')
    loaded=rpc(core,'listwallets');primary=digest({'local_retirement_history':key})
    for ident,job in jobs.items():
        name=job.get('wallet');expected={primary,digest({'local_retirement_source_history':key,'wallet':name})}
        if ident not in expected or job.get('local_only') is not True or job.get('staged') or job.get('state')!='pending' or name not in loaded:raise ValueError('A staged/attempted/unrelated recovery job must be retained.')
        info=rpc(core,'getwalletinfo',[],name)
        if info.get('scanning') is not False or bool(info.get('private_keys_enabled'))!=job.get('expected_private_keys'):raise ValueError('Wallet scanning or private-role evidence changed.')
        if descriptors(rpc(core,'listdescriptors',[False],name))!=descriptors(job['details']['public_wallet']):raise ValueError('The existing Core wallet does not match the retained public policy.')
    evidence=digest({'pending':pending,'jobs':jobs,'recovery':saved.get('recovery')})
    with store.edit() as current:
        if deadline is not None and time.monotonic()>=deadline:raise ValueError('Protected cleanup inspection expired.')
        if evidence!=digest({'pending':current.get('pending',{}),'jobs':current.get('history_jobs',{}),'recovery':current.get('recovery')}):raise ValueError('Recovery changed during inspection.')
        if delivery_pending(current) or current.get('active_transfer') or current.get('sync_batch'):raise ValueError('Other work appeared during inspection.')
        current['pending'].pop(key);current.pop('history_jobs',None);current.pop('recovery',None);current.pop('recovery_plan',None)
        current.setdefault('cancelled_requests',{})[key]='retirement'
        current['sync']='Unattempted legacy retirement dismissed locally. Existing Core wallets retained; no history verification or extinction completion claimed.'
    return True

def inspect_request():
    path=root()/REQUEST
    if not path.exists():return False
    enforce();result=None
    try:
        request=json.loads(path.read_text());now=time.monotonic()
        if set(request)!={'nonce','worker','deadline','request_id'} or not hexid(request['nonce']) or not hexid(request['request_id']) or not now<request['deadline']<now+60:return False
        peer={};status=call('status',timeout=10,peer=peer)
        if peer!=request['worker']:return True
        from configuration import Config,discover_cookie
        from node_client import Core
        config=Config().values;config['cookie']=config['cookie'] or discover_cookie()
        dismiss(Store(root()/'state'),Core(config),request['request_id'],status,request['deadline'])
        if call('ui.request_close',timeout=15).get('ok') is not True:raise ValueError('Worker did not confirm safe close.')
        result={'nonce':request['nonce'],'worker':peer,'ok':True}
    except Exception:
        if 'request' in locals() and isinstance(request,dict):result={'nonce':request.get('nonce'),'worker':request.get('worker'),'ok':False}
    if result is not None and path.exists() and json.loads(path.read_text()).get('nonce')==result['nonce']:
        tmp=root()/(RESULT+'.tmp');tmp.write_text(json.dumps(result));tmp.chmod(0o600);tmp.replace(root()/RESULT)
    return True

def request_close(key):
    if not hexid(key):raise ValueError('Invalid legacy request identity.')
    peer={};public=call('service_status',timeout=10,peer=peer)
    if public.get('worker_version')!='2.0.0~dev62' or public.get('viewer_open') is not False or public.get('connected') is not False or public.get('status_pending'):raise ValueError('Expected a disconnected Build 62 worker with no viewer. Nothing cleared.')
    nonce=secrets.token_hex(32);request=root()/REQUEST;result=root()/RESULT
    result.unlink(missing_ok=True)
    fd=os.open(request,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as out:json.dump({'nonce':nonce,'worker':peer,'deadline':time.monotonic()+45,'request_id':key},out)
        call('ui.arm',timeout=10)
        actual={};call('service_status',timeout=10,peer=actual)
        if actual!=peer:raise ValueError('The worker changed. No inspection was started.')
        call('ui.open','authorise',timeout=15);deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if result.exists():
                value=json.loads(result.read_text())
                if value!={'nonce':nonce,'worker':peer,'ok':True}:raise ValueError('The protected inspection refused cleanup. All wallets were retained; inspect the remaining work.')
                actual={};call('service_status',timeout=10,peer=actual)
                if actual!=peer:raise ValueError('The worker changed. No service was stopped.')
                from secure_bridge import stop
                return stop()
            time.sleep(.1)
        raise ValueError('Protected inspection did not finish. Nothing was force-stopped.')
    finally:request.unlink(missing_ok=True);result.unlink(missing_ok=True)
