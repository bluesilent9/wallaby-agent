"""Independent Core-built legacy policy fixture; no production Vault Builder exists."""
import time
from decimal import Decimal
from vendor.embit.descriptor import Descriptor
from vendor.embit.descriptor.checksum import checksum
from wallet_ops import rpc,install_vault

def proposal(ops,source,destination,height=None):
    core=ops.core;chain=rpc(core,'getblockchaininfo');height=height or chain['blocks']+100
    row=next(r for r in rpc(core,'listdescriptors',[False],destination)['descriptors'] if r.get('active') and not r.get('internal') and r['desc'].startswith('wpkh('));key=Descriptor.from_string(row['desc']).derive(0).key.get_public_key().sec().hex();body='wsh(and_v(v:pk('+key+'),after('+str(height)+')))';desc=body+'#'+checksum(body);address=rpc(core,'deriveaddresses',[desc])[0]
    vault={'version':1,'chain':chain['chain'],'descriptor':desc,'address':address,'height':height,'source':{'descriptor':row['desc'],'index':0},'timestamp':int(time.time())-7200};install_vault(core,vault,ops.store,destination)
    coins=rpc(core,'listunspent',[1],source);inputs=[{'txid':u['txid'],'vout':u['vout'],'sequence':4294967294} for u in coins];amount=sum(Decimal(str(u['amount'])) for u in coins);built=rpc(core,'walletcreatefundedpsbt',{'inputs':inputs,'outputs':[{address:str(amount)}],'options':{'add_inputs':False,'subtractFeeFromOutputs':[0],'fee_rate':'2','replaceable':False}},source)
    return {'vault':vault,'psbt':built['psbt'],'review':ops.review(built['psbt'],source,chain['chain'])}

def fund(ops,source,password,psbt):
    core=ops.core;rpc(core,'walletpassphrase',[password,30],source)
    try:signed=rpc(core,'walletprocesspsbt',[psbt],source);final=rpc(core,'finalizepsbt',[signed['psbt']]);return rpc(core,'sendrawtransaction',[final['hex']])
    finally:rpc(core,'walletlock',[],source)
