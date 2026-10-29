"""Build 8 compose-before-sign checks, always recalculated through local Core."""
from collections import Counter
from wallet_ops import rpc,sats,verify_vault
from vault_policy import public_vault

def unsigned(core,psbt):
    d=rpc(core,'decodepsbt',[psbt])
    for i in d['inputs']:
        if any(i.get(k) for k in ('partial_signatures','final_scriptSig','final_scriptwitness','taproot_key_path_sig','taproot_script_path_sigs')):raise ValueError('Transaction Builder requires a completely unsigned PSBT. Compose before signing.')
    return d

def intents(ops,p,review):
    final=rpc(ops.core,'decodepsbt',[p['psbt']])['tx'];required_fee=0;used=set();outputs=Counter((o['scriptPubKey']['hex'],sats(o['value'])) for o in final['vout'])
    declared=list(p.get('vault_intents',[]))
    final_points={(i['txid'],i['vout']) for i in review['inputs']}
    for saved in ops.store.read().get('vault_proposals',{}).values():
        original=unsigned(ops.core,saved['psbt'])['tx']
        if final_points & {(i['txid'],i['vout']) for i in original['vin']}:
            if p['kind']=='broadcast_transaction':declared.append({'vault':saved['vault'],'proposal_psbt':saved['psbt']})
            if not any(i['vault']==saved['vault'] and unsigned(ops.core,i['proposal_psbt'])['tx']==original for i in declared):raise ValueError('A locally exported vault intent was omitted or changed by Dashboard.')
    for intent in declared:
        v=public_vault(intent['vault']);verify_vault(ops.core,v)
        if v['chain']!=p['chain']:raise ValueError('Vault intent network mismatch.')
        original=unsigned(ops.core,intent['proposal_psbt'])['tx']
        if final['version']!=original['version'] or final['locktime']!=original['locktime'] or (final['locktime']<500000000)!=(original['locktime']<500000000):raise ValueError('Vault intent version or locktime changed.')
        total=0
        for vin in original['vin']:
            key=(vin['txid'],vin['vout'])
            matches=[i for i in review['inputs'] if (i['txid'],i['vout'])==key and i['sequence']==vin['sequence']]
            if key in used or len(matches)!=1:raise ValueError('A fixed vault input was changed, duplicated or removed.')
            used.add(key);total+=int(matches[0]['sats'])
        if len(original['vout'])!=1 or original['vout'][0]['scriptPubKey'].get('address')!=v['address']:raise ValueError('A vault intent must fund its exact mandatory-height policy.')
        for out in original['vout']:
            key=(out['scriptPubKey']['hex'],sats(out['value']))
            if not outputs[key]:raise ValueError('A fixed vault output or amount was changed or removed.')
            outputs[key]-=1;total-=key[1]
        if total<=0:raise ValueError('Invalid fixed vault fee.')
        required_fee+=total
    if int(review['fee_sats'])<required_fee:raise ValueError('The final transaction reduced the fixed vault fee.')


def has_signatures(psbt):
    """Bounded BIP174 input-map scan for upgrade quarantine, without Core or signing."""
    import base64,io
    from vendor.embit.transaction import Transaction
    from vault_policy import psbt_text
    stream=io.BytesIO(base64.b64decode(psbt_text(psbt),validate=True))
    if stream.read(5)!=b'psbt\xff':raise ValueError('Invalid PSBT.')
    def size():
        b=stream.read(1)
        if not b:raise ValueError('Truncated PSBT map.')
        n=b[0]
        if n<253:return n
        count={253:2,254:4,255:8}[n];v=stream.read(count)
        if len(v)!=count:raise ValueError('Truncated PSBT size.')
        return int.from_bytes(v,'little')
    def fields():
        result={}
        while True:
            n=size()
            if not n:return result
            if n>8192:raise ValueError('Oversized PSBT key.')
            key=stream.read(n);length=size()
            if length>2*1024*1024:raise ValueError('Oversized PSBT value.')
            value=stream.read(length)
            if len(key)!=n or len(value)!=length or key in result:raise ValueError('Invalid or duplicate PSBT field.')
            result[key]=value
    global_map=fields()
    if b'\x00' not in global_map:raise ValueError('PSBT v0 is required.')
    tx=Transaction.parse(global_map[b'\x00']);signed=False
    for _ in tx.vin:
        scope=fields();signed=bool(signed or any(k[0] in (2,7,8,19,20) for k in scope))
    for _ in tx.vout:fields()
    if stream.read(1):raise ValueError('Unexpected trailing PSBT data.')
    return signed
