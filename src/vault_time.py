"""Advisory height forecasts from local block headers; never part of signing policy."""
import time
from datetime import datetime, timezone
from wallet_ops import rpc

LOOKBACK = 157788  # Approximately three years at Bitcoin's target block interval.

def estimates(core, heights, now=None, expected_chain=None):
    heights=sorted({h for h in heights if type(h) is int and 0<h<500000000})
    if not heights:return []
    now=time.time() if now is None else now
    try:
        chain=rpc(core,'getblockchaininfo')
        if expected_chain is not None and chain.get('chain')!=expected_chain:
            return [{'height':h,'status':'unavailable','notice':'The proposed Bitcoin network differs from this local node; no unlock date is estimated.'} for h in heights]
        tip=chain['blocks']
        if type(tip) is not int or tip<0:raise ValueError('Invalid tip.')
        header=rpc(core,'getblockheader',[rpc(core,'getblockhash',[tip])])
        latest=header['time']
        if type(latest) is not int or latest<=0:raise ValueError('Invalid header timestamp.')
    except (ValueError,KeyError,TypeError,OSError):
        return [{'height':h,'status':'unavailable','notice':'Local block headers are unavailable; no unlock date can be estimated.'} for h in heights]
    seconds=600.;sample=0;span=0;source='Bitcoin target interval fallback (10 minutes per block)'
    if tip>=144:
        first=max(0,tip-LOOKBACK)
        try:
            older=rpc(core,'getblockheader',[rpc(core,'getblockhash',[first])])['time']
            if type(older) is not int:raise ValueError('Invalid historical timestamp.')
            average=(latest-older)/(tip-first)
            # Accelerated test chains and invalid timestamp spans do not model wall-clock mining.
            if not 60<=average<=3600:raise ValueError('Unrepresentative timestamp span.')
            seconds=average;sample=tip-first;span=latest-older;source='Local block-header timestamp average'
        except (ValueError,KeyError,TypeError,OSError):pass
    warning='Rough estimate only. Mining times vary; the block-height rule, not this date, controls spending. No Dashboard forecast or online time lookup is used.'
    if chain.get('initialblockdownload') or chain.get('headers',tip)>tip or latest<now-7200:
        warning+=' This node is catching up or its tip is stale; the estimate may be especially inaccurate.'
    result=[]
    for height in heights:
        # CLTV nLockTime >= height is final only in a candidate block strictly above height.
        reached=tip>=height;stamp=max(now,float(latest))+max(0,height+1-tip)*seconds
        
        try:utc=datetime.fromtimestamp(stamp,timezone.utc);local=utc.astimezone()
        except (ValueError,OverflowError,OSError):
            result.append({'height':height,'status':'unavailable','notice':'This height is too distant for a useful calendar estimate.'});continue
        result.append({'height':height,'first_spend_block':height+1,'tip_height':tip,'status':'height_reached' if reached else 'estimated','utc':utc.isoformat(timespec='minutes'),'local':local.isoformat(timespec='minutes'),'local_zone':local.tzname(),'seconds_per_block':round(seconds,2),'sample_blocks':sample,'sample_days':round(span/86400,1),'source':source,'notice':warning})
    return result

def for_review(core,review,proposal):
    heights=[o['vault_policy']['height'] for o in review['outputs'] if o.get('vault_policy')]
    heights += [p['height'] for i in review['inputs'] for p in i.get('vault_policies',[])]
    # Called only after transaction_requests.intents has independently verified these intents.
    heights += [i['vault']['height'] for i in proposal.get('vault_intents',[])]
    return estimates(core,heights)
