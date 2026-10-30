"""Recognise the restricted shared policies directly from trusted local Core.

The persisted Core public descriptor is authoritative after RAM-session restart.
Dashboard names never establish a signing role; every account is matched locally.
"""
import re
from wallet_ops import rpc
from build8_policy import descriptors
from vendor.embit.descriptor import Descriptor
from vendor.embit.descriptor.checksum import checksum

def restricted(desc):
    body=desc.split('#')[0];height=None
    match=re.fullmatch(r'wsh\(and_v\(v:after\(([1-9][0-9]{0,8})\),(multi\([^()]+\)|pk\([^()]+\))\)\)',body)
    if match:height=int(match[1]);spend=match[2]
    elif body.startswith('wsh(sortedmulti(') and body.endswith('))'):spend=body[4:-1]
    elif body.startswith('wpkh(') and body.endswith(')'):spend=None
    else:return None
    parsed=Descriptor.from_string(body)
    if any(k.is_private for k in parsed.keys) or not 1<=len(parsed.keys)<=15:return None
    if spend and (spend.startswith('sortedmulti(') or spend.startswith('multi(')):threshold=int(spend.split('(',1)[1].split(',',1)[0])
    else:threshold=1
    if not 1<=threshold<=len(parsed.keys):return None
    accounts=[k.key.to_base58() if hasattr(k.key,'to_base58') else k.get_public_key().sec().hex() for k in parsed.keys]
    if len(set(accounts))!=len(accounts):return None
    return {'height':height,'threshold':threshold,'total':len(parsed.keys),'keys':parsed.keys}

def inventory(core):
    loaded=rpc(core,'listwallets');private=[];monitors=[]
    for name in loaded:
        if rpc(core,'getwalletinfo',[],name).get('private_keys_enabled'):private.append((name,descriptors(rpc(core,'listdescriptors',[False],name))))
        else:monitors.append(name)
    return {'private':private,'monitors':monitors,'addresses':{}}

def matches(core,store,address,known=None):
    if not address:return []
    known=inventory(core) if known is None else known
    if address in known['addresses']:return known['addresses'][address]
    result=[];private=known['private']
    for monitor in known['monitors']:
        info=rpc(core,'getaddressinfo',[address],monitor)
        if not (info.get('ismine') or info.get('iswatchonly')) or not info.get('parent_desc'):continue
        desc=info['parent_desc'];parsed=restricted(desc)
        if not parsed:continue
        wallets=[]
        for name,local in private:
            for key in parsed['keys']:
                body='wpkh('+str(key)+')';raw={'wallet_name':name,'descriptors':[{'desc':body+'#'+checksum(body)}]}
                if descriptors(raw)<=local:
                    wallets.append(name);break
        if wallets:
            from setup_completion import PENDING,READY
            address0=rpc(core,'deriveaddresses',[desc,[0,0]])[0] if Descriptor.from_string(desc).is_wildcard else address
            labels=rpc(core,'getaddressinfo',[address0],monitor).get('labels',[])
            setup_monitor=bool(re.fullmatch(r'Wallaby policy [0-9a-f]{20}',monitor))
            ready=not any(label.startswith(PENDING) for label in labels) and (not setup_monitor or any(label.startswith(READY) for label in labels))
            result.append({k:v for k,v in parsed.items() if k!='keys'}|{'wallets':wallets,'monitor_wallet':monitor,'setup_ready':ready})
    known['addresses'][address]=result
    return result

def monitors_for_key(core,name):
    local=descriptors(rpc(core,'listdescriptors',[False],name));result=[]
    for monitor in rpc(core,'listwallets'):
        if rpc(core,'getwalletinfo',[],monitor).get('private_keys_enabled'):continue
        for row in rpc(core,'listdescriptors',[False],monitor)['descriptors']:
            parsed=restricted(row['desc'])
            if not parsed:continue
            for key in parsed['keys']:
                body='wpkh('+str(key)+')'
                if descriptors({'wallet_name':name,'descriptors':[{'desc':body+'#'+checksum(body)}]})<=local:
                    result.append(monitor);break
            if monitor in result:break
    return result

def signers_for_policy(core,raw):
    known=inventory(core);owners=set()
    for row in raw['descriptors']:
        parsed=restricted(row['desc'])
        if not parsed:return []
        matching=set()
        for key in parsed['keys']:
            body='wpkh('+str(key)+')';wanted=descriptors({'wallet_name':'key','descriptors':[{'desc':body+'#'+checksum(body)}]})
            matching.update(name for name,local in known['private'] if wanted<=local)
        if not matching:return []
        owners|=matching
    return sorted(owners)
