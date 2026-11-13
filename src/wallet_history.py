"""Read-only local Core ledger. No Server, fiat, private descriptors or block replay."""
from collections import defaultdict
from decimal import Decimal
from wallet_ops import rpc,sats
from wallet_labels import address_only,read_labels

def signed_sats(value):
    number=Decimal(str(value))
    return -sats(-number) if number<0 else sats(number)

def transactions(core,wallet):
    if not isinstance(wallet,str) or wallet not in rpc(core,'listwallets'):raise ValueError('This wallet is no longer loaded on this node.')
    info=rpc(core,'getwalletinfo',[],wallet)
    if info.get('scanning'):raise ValueError('Wallet history is scanning. Wait for Core to finish before opening its transaction table.')
    raw=rpc(core,'listdescriptors',[False],wallet)
    extinct=info.get('private_keys_enabled') is False and address_only(raw)
    labels={r['address']:r['label'] for r in read_labels(core,wallet,raw,[])} if extinct else {}
    seen=set();offset=0
    while True:
        batch=rpc(core,'listtransactions',['*',1000,offset,True],wallet)
        seen.update(r['txid'] for r in batch)
        if len(batch)<1000:break
        offset+=len(batch)
        if offset>50000:raise ValueError('This wallet exceeds the local history table limit. No partial balances were displayed.')
    cache={}
    def tx(ident):
        if ident not in cache:
            value=rpc(core,'gettransaction',[ident,True,True],wallet)
            if not value.get('decoded'):value['decoded']=rpc(core,'decoderawtransaction',[value['hex']])
            cache[ident]=value
        return cache[ident]
    ownership={}
    def owned(address):
        if not address:return False
        if address not in ownership:
            facts=rpc(core,'getaddressinfo',[address],wallet)
            ownership[address]=bool(facts.get('ismine') or facts.get('iswatchonly'))
        return ownership[address]
    def group(address):return labels.get(address,'').split(' | LOST:',1)[0].strip() or 'Unlabelled historical wallet'
    groups=defaultdict(list)
    for ident in sorted(seen):
        value=tx(ident)
        if value.get('confirmations',0)<0 or value.get('abandoned'):continue
        decoded=value['decoded'];outputs=decoded.get('vout',[]);movements=defaultdict(int)
        if extinct:
            for output in outputs:
                address=output['scriptPubKey'].get('address')
                if owned(address):movements[group(address)]+=sats(output['value'])
            for inp in decoded.get('vin',[]):
                prev=inp.get('txid')
                if prev not in seen:continue # An external input is outside this wallet's recorded history.
                parent=tx(prev)['decoded']['vout'][inp['vout']];address=parent['scriptPubKey'].get('address')
                if owned(address):movements[group(address)]-=sats(parent['value'])
        else:
            delta=signed_sats(value.get('amount',0))+signed_sats(value.get('fee',0))
            if value.get('generated') and not delta:delta=sum(signed_sats(d.get('amount',0)) for d in value.get('details',[]) if d.get('category')=='immature')
            movements[wallet]=delta
        stamp=int(value.get('blocktime') or value.get('time') or value.get('timereceived') or 0)
        for name,delta in movements.items():
            if delta<0:
                addresses=sorted({o['scriptPubKey']['address'] for o in outputs if o['scriptPubKey'].get('address') and (not owned(o['scriptPubKey']['address']) or extinct and group(o['scriptPubKey']['address'])!=name)})
                if not addresses:addresses=sorted({r['address'] for r in value.get('details',[]) if r.get('category')=='send' and r.get('address')})
            else:addresses=sorted({o['scriptPubKey']['address'] for o in outputs if o['scriptPubKey'].get('address') and owned(o['scriptPubKey']['address']) and (not extinct or group(o['scriptPubKey']['address'])==name)})
            groups[name].append({'txid':ident,'timestamp':stamp,'addresses':addresses,'amount_sats':str(delta),'confirmations':value.get('confirmations',0)})
    result=[]
    # Keep empty legacy groups visible without inventing any historical transactions.
    if extinct:
        for address in labels:groups[group(address)]
    elif wallet not in groups:groups[wallet]
    for name,rows in groups.items():
        balance=0
        for row in sorted(rows,key=lambda r:(r['timestamp'],r['txid'])):
            balance+=int(row['amount_sats']);row['balance_sats']=str(balance)
        result.append({'name':name,'latest':max((r['timestamp'] for r in rows),default=0),'rows':sorted(rows,key=lambda r:(r['timestamp'],r['txid']),reverse=True)})
    result.sort(key=lambda g:(-g['latest'],g['name'].casefold()))
    response={'wallet':wallet,'extinct':extinct,'groups':result,'notice':'Core’s currently recorded transaction history, including pending and immature transactions. Amounts include wallet fee deductions. This view does not start a rescan or certify complete archival coverage.'}
    if len(__import__('json').dumps(response))>16*1024*1024:raise ValueError('This wallet exceeds the local history table size limit. No partial balances were displayed.')
    return response
