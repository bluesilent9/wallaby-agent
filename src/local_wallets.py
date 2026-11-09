"""Local user deletion only. Never dispatched from a Wallet Server RPC or proposal."""
import secrets,time
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc,sats
import wallet_deletion

class LocalWallets:
    def __init__(self,core,guard):self.core=core;self.guard=guard;self.reviews={}
    def facts(self,name):
        if not isinstance(name,str) or name not in rpc(self.core,'listwallets'):raise ValueError('Refresh the wallets on this node before deleting one.')
        info=rpc(self.core,'getwalletinfo',[],name)
        balances=rpc(self.core,'getbalances',[],name)
        total=sum(sats(section.get(k,0)) for section in balances.values() if isinstance(section,dict) for k in ('trusted','untrusted_pending','immature'))
        raw=rpc(self.core,'listdescriptors',[False],name)
        from managed_accounts import classify
        store=getattr(self.core,'managed_store',None)
        # A blank local Core wallet is valid but has no policy to classify.
        # Keep the remote public-inventory validator strict.
        managed=classify(store.read() if store is not None else {},name,raw) if raw.get('descriptors') else None
        store=getattr(self.core,'managed_store',None)
        if store is not None:
            from sync_table import observe
            observe(store,'listdescriptors',name,raw);observe(store,'getwalletinfo',name,{**info,'wallaby_managed':managed})
        from wallet_traits import local_traits
        return {'traits':local_traits(self.core,[name],raw=raw),'managed':managed,'wallet':name,'sats':str(total),'private_keys_enabled':info.get('private_keys_enabled') is True,'encrypted':'unlocked_until' in info,'scanning':bool(info.get('scanning')),'format':info.get('format'),'storage':info.get('wallaby_storage','node'),'balances':balances,'policy':digest(rpc(self.core,'listdescriptors',[False],name))}
    def source(self,name):
        source=wallet_deletion.target(self.core,name,allow_extinct=True)
        if Path(source['path']).parent not in wallet_deletion.bases():raise ValueError('This wallet uses a custom or RAM-only location. Manage it at its source; it cannot be deleted from these cards.')
        return source
    def listing(self):
        rows=[]
        names=rpc(self.core,'listwallets')
        store=getattr(self.core,'managed_store',None)
        if store is not None:__import__('sync_table').observe(store,'listwallets',None,names)
        for name in sorted(names,key=str.casefold):
            try:
                facts=self.facts(name);reason=''
                if facts['storage']=='disc':continue
                try:
                    self.source(name)
                    if facts['format']!='sqlite' or facts['scanning']:raise ValueError('Wait for wallet scanning to finish. Only standard SQLite wallet directories can be deleted here.')
                except ValueError as e:reason=str(e)
                rows.append({k:facts[k] for k in ('wallet','sats','private_keys_enabled','traits')}|{'deletable':not reason,'reason':reason,**({'managed':facts['managed']} if facts.get('managed') else {})})
            except ValueError:rows.append({'wallet':name,'sats':None,'private_keys_enabled':None,'deletable':False,'reason':'Core could not confirm this wallet. Refresh after its current operation finishes.'})
        return {'wallets':rows}
    def review(self,name):
        self.guard();facts=self.facts(name)
        if facts['storage']!='node' or facts['scanning'] or facts['format']!='sqlite':raise ValueError('Finish scanning before deleting a standard SQLite wallet.')
        source=self.source(name);token=secrets.token_hex(32)
        self.reviews={k:v for k,v in self.reviews.items() if time.monotonic()-v[2]<120}
        self.reviews[token]=(facts,source,time.monotonic())
        return {'token':token,**{k:facts[k] for k in ('wallet','sats','private_keys_enabled')}}
    def delete(self,token,confirmed):
        if confirmed is not True or not isinstance(token,str):raise ValueError('Confirm the exact local wallet before deleting it.')
        self.guard();saved=self.reviews.get(token)
        if not saved or time.monotonic()-saved[2]>120:raise ValueError('Deletion confirmation expired. Review the wallet again; nothing was deleted.')
        facts,source,_=saved;name=facts['wallet']
        if facts!=self.facts(name) or source!=self.source(name):raise ValueError('The wallet changed after review. Refresh and confirm it again; nothing was deleted.')
        # A confirmed deletion is never replayed after an uncertain response.
        self.reviews.pop(token)
        try:
            if facts['encrypted'] and facts['private_keys_enabled']:rpc(self.core,'walletlock',[],name)
            rpc(self.core,'unloadwallet',{'wallet_name':name,'load_on_startup':False})
            wallet_deletion.delete(source,manual=True)
            if name in rpc(self.core,'listwallets') or name in [r['name'] for r in rpc(self.core,'listwalletdir')['wallets']]:raise ValueError('Core still lists the wallet.')
        except Exception:raise ValueError('Local wallet deletion was not confirmed. It may have been unloaded or deleted. Inspect Core and refresh; no deletion was automatically retried.') from None
        return {'message':'Deleted the local wallet “'+name+'”. Other nodes and archival discs are unchanged. This does not disable future synchronisation requests.','wallet':name}
