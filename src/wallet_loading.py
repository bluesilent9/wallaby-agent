"""Temporarily inspect local Core wallets without changing startup preferences."""
from contextlib import contextmanager
from functools import wraps
from wallet_ops import rpc
from activity_log import event
from diagnostics import LocalActionFailure

@contextmanager
def ownership_wallets(core,names=None):
    loaded=set(rpc(core,'listwallets'));directories={r['name'] for r in rpc(core,'listwalletdir')['wallets']}
    if names is not None:directories.intersection_update(names)
    temporary=[];failed=False
    try:
        if directories-loaded:event('sync.wallet_loading','Ownership inspection started · pending_wallets='+str(len(directories-loaded)))
        for name in sorted(directories-loaded):
            temporary.append(name)
            try:rpc(core,'loadwallet',{'filename':name},timeout=600)
            except Exception as error:
                reason='history_unavailable' if any(word in str(error).lower() for word in ('prun','rescan')) else 'wallet_unavailable'
                event('sync.wallet_loading','Ownership inspection stopped · stage=load · reason='+reason+' · exception='+type(error).__name__+' · attempted_count='+str(len(temporary)))
                raise LocalActionFailure('ownership_wallet_load','Core could not load a local wallet for the ownership check. No history was imported; check the Agent log and local Core wallet status.') from None
        if temporary:event('sync.wallet_loading','Ownership inspection prepared · temporary_wallets='+str(len(temporary)))
        yield
    except BaseException:
        failed=True;raise
    finally:
        failures=0;unloaded=0
        try:current=set(rpc(core,'listwallets'))
        except Exception:current=set(temporary)
        for name in reversed(temporary):
            if name not in current:continue
            try:rpc(core,'unloadwallet',{'wallet_name':name},timeout=600);unloaded+=1
            except Exception:failures+=1
        if temporary:event('sync.wallet_loading','Ownership inspection cleanup · unloaded='+str(unloaded)+' · failures='+str(failures))
        if failures and not failed:raise LocalActionFailure('ownership_wallet_cleanup','Core could not restore every temporarily loaded wallet to its prior unloaded state. Check the Agent log and synchronisation status for the wallet outcome; no operation was retried.')

def inspect_local_wallets(function):
    @wraps(function)
    def wrapped(core,*args,**kwargs):
        with ownership_wallets(core):return function(core,*args,**kwargs)
    return wrapped
