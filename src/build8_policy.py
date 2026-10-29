"""Strict public Build 8 messages; remote names/addresses never grant authority."""
import ipaddress,re,json
from vault_policy import text,psbt_text,public_vault,NETWORK
from vendor.embit.descriptor import Descriptor
from vendor.embit.descriptor.checksum import checksum
from agent_rpc import PRIVATE

def ipv6(value):
    if not isinstance(value,str) or '%' in value:raise ValueError('A routable IPv6 address is required.')
    a=ipaddress.IPv6Address(value)
    if a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified or a.ipv4_mapped:raise ValueError('A routable IPv6 address is required.')
    return str(a)

def descriptors(raw):
    if not isinstance(raw,dict) or set(raw)-{'wallet_name','descriptors'} or not isinstance(raw.get('descriptors'),list) or not 1<=len(raw['descriptors'])<=256:raise ValueError('Invalid public wallet inventory.')
    name=raw.get('wallet_name')
    if not isinstance(name,str) or len(name)>256 or any(ord(c)<32 for c in name):raise ValueError('Invalid public wallet name.')
    keys=set();derived_count=0
    for row in raw['descriptors']:
        if not isinstance(row,dict) or 'desc' not in row or set(row)-{'desc','timestamp','active','internal','range','next','next_index'}:raise ValueError('Invalid public descriptor fields.')
        if ('timestamp' in row and (type(row['timestamp']) is not int or not 0<=row['timestamp']<=4102444800)) or ('active' in row and type(row['active']) is not bool):raise ValueError('Invalid descriptor timestamp or activity.')
        if 'internal' in row and type(row['internal']) is not bool:raise ValueError('Invalid descriptor branch.')
        if 'range' in row:
            r=row['range']
            if not isinstance(r,list) or len(r)!=2 or any(type(v) is not int for v in r) or not 0<=r[0]<=r[1]<2**31:raise ValueError('Invalid descriptor range.')
            derived_count+=r[1]-r[0]+1
            if derived_count>100000:raise ValueError('Descriptor ranges exceed the safe automatic import limit.')
        for key in ('next','next_index'):
            if key in row and (type(row[key]) is not int or not 0<=row[key]<2**31):raise ValueError('Invalid next address index.')
        desc=text(row['desc'],8192);body,sep,check=desc.partition('#')
        if PRIVATE.search(desc) or not sep or checksum(body)!=check:raise ValueError('Only checksummed public descriptors are accepted.')
        if body.startswith('addr('):
            from wallet_labels import fixed_address
            if not fixed_address(desc):raise ValueError('Invalid fixed-address descriptor.')
            keys.add(body);continue
        d=Descriptor.from_string(body)
        if not d.keys or any(k.is_private for k in d.keys):raise ValueError('A public-key wallet is required.')
        keys.add(re.sub(r'\[[^\]]*\]','',body).replace("'",'h'))
    return keys

def proposal(p):
    kind=p.get('kind')
    if kind=='wallet_sync_queue':
        if set(p)!={'kind','revision','requests'} or type(p['revision']) is not int or p['revision']<0 or not isinstance(p['requests'],list) or len(p['requests'])>128:raise ValueError('Invalid synchronisation list.')
        ids=set()
        for request in p['requests']:
            if not isinstance(request,dict) or request.get('kind')!='wallet_transfer':raise ValueError('Only wallet transfer rows are allowed.')
            proposal(request)
            if request['transfer_id'] in ids:raise ValueError('Duplicate wallet transfer.')
            ids.add(request['transfer_id'])
        return p
    if kind=='node_identity' and set(p)=={'kind'}:return p
    if kind=='wallet_transfer':
        if not {'kind','direction','transfer_id','peer','public_wallet','source_has_private_keys','earliest_timestamp','requires_blockchain_redownload'}<=set(p)<={'kind','direction','transfer_id','peer','public_wallet','source_has_private_keys','earliest_timestamp','requires_blockchain_redownload','preview_challenge','node_ipv6','transfer_version'}:raise ValueError('Invalid paired transfer request.')
        if p['direction'] not in ('send','receive') or not re.fullmatch('[0-9a-f]{64}',p['transfer_id']):raise ValueError('Invalid transfer identity.')
        if ('preview_challenge' in p)!=('node_ipv6' in p):raise ValueError('Both preview negotiation fields are required.')
        if 'preview_challenge' in p:
            if not re.fullmatch('[0-9a-f]{64}',str(p['preview_challenge'])):raise ValueError('Invalid preview challenge.')
            ipv6(p['node_ipv6'])
        if 'transfer_version' in p and (type(p['transfer_version']) is not int or p['transfer_version']!=2):raise ValueError('Unsupported direct transfer version.')
        peer=p['peer']
        if not isinstance(peer,dict) or set(peer)!={'node_id','hostname','ipv6'}:raise ValueError('Invalid peer identity.')
        text(peer['node_id']);text(peer['hostname']);ipv6(peer['ipv6']);descriptors(p['public_wallet'])
        from wallet_labels import fixed_address
        if any(fixed_address(row['desc']) for row in p['public_wallet']['descriptors']) and p['source_has_private_keys']:raise ValueError('Fixed-address records require a private-key-disabled watch wallet.')
        if type(p['source_has_private_keys']) is not bool or type(p['requires_blockchain_redownload']) is not bool or type(p['earliest_timestamp']) is not int or not 0<=p['earliest_timestamp']<=4102444800:raise ValueError('Invalid transfer history.')
    elif kind=='wallet_transfer_preview':
        if set(p)!={'kind','preview','public_key','signature'}:raise ValueError('Invalid preview delivery.')
        from wallet_preview import validate_preview
        validate_preview({k:p[k] for k in ('preview','public_key','signature')})
    elif kind in ('sign_psbt_partial','broadcast_transaction'):
        required={'kind','request_id','chain','psbt'}|({'wallet'} if kind=='sign_psbt_partial' else {'txid'})
        allowed=required|({'vault_intents'} if kind=='sign_psbt_partial' else set())
        if not required<=set(p)<=allowed or not re.fullmatch('[0-9a-f]{64}',p['request_id']) or p['chain'] not in NETWORK:raise ValueError('Invalid transaction request.')
        psbt_text(p['psbt'])
        if kind=='broadcast_transaction':
            if not re.fullmatch('[0-9a-f]{64}',p['txid']):raise ValueError('Invalid expected transaction ID.')
        else:
            if not isinstance(p['wallet'],str) or len(p['wallet'])>256 or any(ord(c)<32 for c in p['wallet']):raise ValueError('Invalid RPC wallet name.')
            intents=p.get('vault_intents',[])
            if not isinstance(intents,list) or len(intents)>16:raise ValueError('Invalid vault intents.')
            for i in intents:
                if not isinstance(i,dict) or set(i)!={'vault','proposal_psbt'}:raise ValueError('Invalid vault intent.')
                public_vault(i['vault']);psbt_text(i['proposal_psbt'])
    else:raise ValueError('Unsupported Dashboard operation.')
    if PRIVATE.search(json.dumps(p)):raise ValueError('Private material is forbidden in Dashboard messages.')
    return p
