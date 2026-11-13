"""Presentation facts derived only from local Core and its local disc router."""
from vendor.embit.descriptor import Descriptor

def policy_traits(desc):
    try:
        parsed=Descriptor.from_string(desc.split('#')[0])
        if any(key.is_private for key in parsed.keys):return {}
        from wallet_setup_signing import restricted
        policy=restricted(desc)
        threshold=policy['threshold'] if policy else int(str(parsed.miniscript.args[0])) if parsed.is_basic_multisig else 1
        return {'vault':bool(policy and policy['height'] is not None),'multisig':threshold>1}
    except (ValueError,TypeError,IndexError,AttributeError):return {}

def local_traits(core,names,address=None,raw=None,cache=None):
    from wallet_ops import rpc
    cache={} if cache is None else cache
    flags={'vault':False,'multisig':False,'watch':False,'disc':False}
    private=False;known=False
    for name in names:
        if name not in cache:cache[name]=rpc(core,'getwalletinfo',[],name)
        info=cache[name];known=True;private=private or info.get('private_keys_enabled') is True
        flags['disc']=flags['disc'] or info.get('wallaby_storage')=='disc'
        if address:
            facts=rpc(core,'getaddressinfo',[address],name)
            policies=[facts.get('parent_desc','')]
        else:
            descriptors=raw if raw is not None else rpc(core,'listdescriptors',[False],name)
            policies=[r['desc'] for r in descriptors.get('descriptors',[])]
        for desc in policies:
            for key,value in policy_traits(desc).items():flags[key]=flags[key] or value
    flags['watch']=known and not private
    return flags


def source_storage(core,p):
    from peer_wallet import source_wallet
    from wallet_ops import rpc
    if __import__('extinct_sync').grouped(p['public_wallet']):return 'node'
    name=source_wallet(core,p,public_preview=True)
    return 'disc' if rpc(core,'getwalletinfo',[],name).get('wallaby_storage')=='disc' else 'node'

def sync_traits(raw):
    from extinct_sync import grouped
    flags={'vault':False,'multisig':False,'extinct':grouped(raw),'smsf':'smsf' in raw.get('wallet_name','').casefold(),'disc':False}
    for row in raw.get('descriptors',[]):
        for key,value in policy_traits(row['desc']).items():flags[key]|=value
        try:flags['multisig']|=len(Descriptor.from_string(row['desc'].split('#')[0]).keys)>1
        except (ValueError,TypeError,AttributeError):pass
    return flags
