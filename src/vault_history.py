"""Fund-specific vault state from local Core policies and unspent outputs."""
import math
from wallet_ops import rpc,sats
from wallet_setup_signing import restricted

def status(core,wallet,raw):
    policies=[r.get('desc','') for r in raw.get('descriptors',[])]
    if not any('after(' in d for d in policies):return None
    error={'state':'error'}
    try:
        parsed=[restricted(d) for d in policies if 'after(' in d]
        if not parsed or any(p is None or p['height'] is None for p in parsed):return error
        chain=rpc(core,'getblockchaininfo');tip=chain['blocks']
        if type(tip) is not int or chain.get('initialblockdownload') or chain.get('headers',tip)>tip:return error
        balances=rpc(core,'getbalances',[],wallet)
        if any(sats(v.get('immature',0)) for v in balances.values()):return error
        coins=rpc(core,'listunspent',[0,9999999,[],True],wallet)
        seen={(c['txid'],c['vout']) for c in coins}
        for c in rpc(core,'listlockunspent',[],wallet):
            if (c['txid'],c['vout']) in seen:continue
            output=rpc(core,'gettxout',[c['txid'],c['vout'],True])
            if output:
                coins.append({'amount':output['value'],'address':output['scriptPubKey'].get('address')})
        heights=[]
        for coin in coins:
            if sats(coin['amount'])<=0:continue
            address=coin.get('address')
            if not address:return error
            facts=rpc(core,'getaddressinfo',[address],wallet)
            if not (facts.get('ismine') or facts.get('iswatchonly')):return error
            # Use this output's policy, including old generations, rather than the active receive policy.
            desc=facts.get('desc') or facts.get('parent_desc','');policy=restricted(desc)
            if policy is None:return error
            heights.append(policy['height'])
        if not heights:return {'state':'unfunded'}
        if all(h is None for h in heights):return error
        locked=[h is not None and h>tip for h in heights]
        if any(h is None for h in heights) or any(locked) and not all(locked):return {'state':'mixed'}
        if not any(locked):return {'state':'unlocked'}
        height=max(heights)
        from vault_time import estimates
        forecast=estimates(core,[height])[0]
        if forecast['status']!='estimated':return error
        return {'state':'locked','seconds':math.ceil((height-tip)*forecast['seconds_per_block']),'height':height,'tip_height':tip,'notice':forecast['notice']}
    except (ValueError,KeyError,TypeError,IndexError,AttributeError,OSError):return error
