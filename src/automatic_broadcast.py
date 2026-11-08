"""Publish already signed transactions; never create signatures or unlock keys."""
import threading,time
from approval_store import digest,MAX_ITEMS
from wallet_ops import rpc
from diagnostics import LocalActionFailure

class Broadcasts:
    def __init__(self,core,store,can_run=lambda:True):self.core=core;self.store=store;self.can_run=can_run;self.lock=threading.Lock();self.thread=None
    @property
    def active(self):return bool(self.thread and self.thread.is_alive())
    def start(self):
        with self.lock:
            if self.active or not self.can_run():return
            keys=[key for key,row in self.store.read()['pending'].items() if row['proposal']['kind']=='broadcast_transaction' and row['state']=='pending'][:4]
            if not keys:return
            self.thread=threading.Thread(target=self.run,args=(keys,),daemon=True,name='signed-transaction-broadcast');self.thread.start()
    def run(self,keys):
        for key in keys:
            try:self.process(key)
            except Exception:
                # A storage failure retains the attempted request. It must not
                # result in an invisible retry of an uncertain send RPC.
                from activity_log import event
                event('transaction.broadcast','Automatic broadcast stopped; local outcome retained. No uncertain send was repeated.')
    def known(self,txid):
        try:
            if isinstance(rpc(self.core,'getmempoolentry',[txid]),dict):return True
        except (ValueError,OSError):pass
        try:
            result=rpc(self.core,'getrawtransaction',[txid,True])
            return isinstance(result,dict) and result.get('txid')==txid and result.get('confirmations',0)>0
        except (ValueError,OSError):return False
    def finish(self,key,p,status,message):
        payload={'request_hash':key,'status':status,'txid':p['txid'],**({'message':message} if status=='error' else {})}
        item={'kind':'broadcast_result','payload':payload};ident=digest(item)
        with self.store.edit() as saved:
            if len(saved['outbox'])>=MAX_ITEMS:raise ValueError('Wallet Server outbox is full; broadcast outcome retained for reconciliation.')
            saved['outbox'][ident]=item
            saved['completed'][key]={'kind':'broadcast_transaction','at':time.time(),'proposal':p,'artifact_psbt':p['psbt'],'artifact_txid':p['txid'],'status':status,'message':message,'automatic':True,'outbox_id':ident,'delivery':'queued'}
            saved['pending'].pop(key,None)
        from activity_log import event
        event('transaction.broadcast',('Core confirmed broadcast' if status=='broadcast' else 'Broadcast refused or uncertain')+' · request='+key[:12])
        return payload
    def process(self,key):
        from cancellation import blocked
        with self.store.edit() as saved:
            row=saved['pending'].get(key)
            if not self.can_run() or not row or row['proposal']['kind']!='broadcast_transaction' or row.get('withdrawn') or blocked(saved,row['proposal']):return
            p=row['proposal']
            if row['state']!='pending':return # Never repeat an attempted send.
            if len(saved['outbox'])>=MAX_ITEMS:return
            row['state']='attempted'
        sending=False
        try:
            if rpc(self.core,'getblockchaininfo')['chain']!=p['chain']:raise LocalActionFailure('broadcast_network','The signed transaction network does not match this node.')
            final=rpc(self.core,'finalizepsbt',[p['psbt']])
            if not isinstance(final,dict) or final.get('complete') is not True or not isinstance(final.get('hex'),str):raise LocalActionFailure('broadcast_unsigned','The PSBT is not fully signed. No transaction was broadcast.')
            if rpc(self.core,'decoderawtransaction',[final['hex']]).get('txid')!=p['txid']:raise LocalActionFailure('broadcast_identity','The completed transaction does not match the requested TXID. Nothing was broadcast.')
            if self.known(p['txid']):return self.finish(key,p,'broadcast','Core already has this exact transaction.')
            verdict=rpc(self.core,'testmempoolaccept',[[final['hex']]])
            if not isinstance(verdict,list) or len(verdict)!=1 or verdict[0].get('allowed') is not True:
                if self.known(p['txid']):return self.finish(key,p,'broadcast','Core already has this exact transaction.')
                raise LocalActionFailure('broadcast_refused','Bitcoin Core did not accept the completed transaction. Check its inputs, fee and locktime; no send was made.')
            # Honour a cancellation received during preflight, before submission.
            current=self.store.read()
            if not self.can_run() or blocked(current,p) or current['pending'].get(key,{}).get('withdrawn'):raise LocalActionFailure('broadcast_cancelled','This broadcast was cancelled before submission. Nothing was sent.')
            sending=True;txid=rpc(self.core,'sendrawtransaction',[final['hex']])
            if txid!=p['txid']:raise ValueError('Unexpected send result.')
        except Exception as error:
            if sending:
                if self.known(p['txid']):return self.finish(key,p,'broadcast','Core confirmed this exact transaction after an interrupted reply.')
                message='Broadcast outcome is uncertain. No send was retried. Check this TXID on the node or Mempool before any new attempt.'
            else:message=str(error) if isinstance(error,LocalActionFailure) else 'Core could not verify the completed transaction. No send was made. Check node readiness and retry from Wallet Server when resolved.'
            return self.finish(key,p,'error',message)
        return self.finish(key,p,'broadcast','Core accepted this exact transaction for broadcast.')
