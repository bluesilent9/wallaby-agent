"""Bounded upgrade inspection. Private state is inspected only inside protection."""
import json,os,secrets,socket,struct,time
from protected_memory import root,enforce

VERSION='2.0.0~dev18'
PROTOCOL=1
REQUEST='upgrade-request.json'
RESULT='upgrade-result.json'

def identity(pid):
    # Linux start ticks disambiguate a PID reused after an exited worker.
    from pathlib import Path
    text=Path('/proc/'+str(pid)+'/stat').read_text()
    return {'pid':pid,'start':text[text.rfind(')')+2:].split()[19]}

def unsupported(error):
    return str(error)=='Unsupported protected action.'

def current(state):
    return isinstance(state,dict) and state.get('worker_version')==VERSION and state.get('worker_protocol')==PROTOCOL

def private_idle(state):
    """Legacy status stays inside the protected process; never return its data."""
    if not isinstance(state,dict) or state.get('busy') is not False:return False
    if not isinstance(state.get('pending'),list) or state['pending'] or not isinstance(state.get('setups'),list) or state['setups']:return False
    archives=state.get('archives')
    if not isinstance(archives,dict) or archives.get('reading') is not False or not isinstance(archives.get('loaded'),list) or archives['loaded'] or not isinstance(archives.get('staged'),list) or archives['staged']:return False
    # Legacy public status hid outbox_count. Inspect the RAM store directly here
    # so denial/preferences notifications do not count as unfinished work.
    from approval_store import Store
    from secure_worker import delivery_pending
    saved=Store(root()/'state').read()
    return not delivery_pending(saved)

def inspect_request():
    """Run in a viewer child of the old service, before creating any Qt window."""
    path=root()/REQUEST
    if not path.exists():return False
    enforce()
    try:
        request=json.loads(path.read_text())
        if set(request)!={'nonce','worker','deadline'} or not isinstance(request['nonce'],str) or len(request['nonce'])!=64 or not time.monotonic()<request['deadline']<time.monotonic()+60:return False
        from secure_bridge import call
        peer={};state=call('status',timeout=8,peer=peer)
        if peer!=request['worker'] or time.monotonic()>=request['deadline']:return True
        ready=private_idle(state)
        result={'nonce':request['nonce'],'worker':peer,'ready':ready}
        temp=root()/(RESULT+'.tmp');temp.write_text(json.dumps(result));temp.chmod(0o600);temp.replace(root()/RESULT)
    except Exception:
        # No private exceptions or wallet data cross the normal-process boundary.
        return True
    return True

def inspect_legacy(peer,timeout=20):
    """Ask the old service to launch its installed protected viewer as inspector."""
    from secure_bridge import call,WorkspaceFailure
    nonce=secrets.token_hex(32);deadline=time.monotonic()+timeout
    request=root()/REQUEST;result=root()/RESULT
    result.unlink(missing_ok=True);request.unlink(missing_ok=True)
    fd=os.open(request,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:json.dump({'nonce':nonce,'worker':peer,'deadline':deadline},stream)
        call('ui.open','authorise',timeout=8)
        while time.monotonic()<deadline:
            if result.exists():
                evidence=json.loads(result.read_text())
                if evidence!={'nonce':nonce,'worker':peer,'ready':True}:raise WorkspaceFailure('upgrade_busy','The older protected workspace contains unfinished work. Its RAM was retained. Finish its requests, deliveries and archival-wallet operations before upgrading.')
                actual={};state=call('service_status',timeout=3,peer=actual)
                if actual!=peer:raise WorkspaceFailure('upgrade_changed','The protected worker changed during inspection. Retry the node toggle; no workspace was stopped.')
                if not state.get('viewer_open') and state.get('busy') is False:return
            time.sleep(.1)
        raise WorkspaceFailure('upgrade_unverified','The older worker could not confirm that its protected RAM is idle. It was retained. Finish existing work, then reboot before reconnecting the node.')
    finally:
        request.unlink(missing_ok=True);result.unlink(missing_ok=True)
