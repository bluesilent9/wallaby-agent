"""BIP-322 messages via local Core accounts, with no private descriptor export.

Only fixed synthetic transactions can reach this path. They spend a nonexistent
message-derived output, never real coins. Partial proofs remain PSBTs until the
script's signature threshold is met. Public ECDSA/Schnorr proofs are checked here.
"""
import base64,hashlib,io,time
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from vendor.embit import ec,script,compact
from vendor.embit.transaction import Transaction,TransactionInput,TransactionOutput
from vendor.embit.descriptor import Descriptor
from wallet_ops import rpc
from wallet_setup_signing import restricted,matches

MAX=1024*1024
ORDER=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

def field(key,value):return compact.to_bytes(len(key))+key+compact.to_bytes(len(value))+value

def maps(text):
    if not isinstance(text,str) or len(text)>MAX*2:raise ValueError('Message PSBT is too large.')
    try:data=base64.b64decode(text,validate=True)
    except Exception:raise ValueError('Invalid message PSBT encoding.') from None
    if len(data)>MAX or not data.startswith(b'psbt\xff'):raise ValueError('Invalid message PSBT.')
    stream=io.BytesIO(data[5:])
    def number():
        first=stream.read(1)
        if not first:raise ValueError('Truncated message PSBT.')
        n=first[0]
        if n<253:return n
        count={253:2,254:4,255:8}[n];raw=stream.read(count)
        if len(raw)!=count:raise ValueError('Truncated message PSBT.')
        val=int.from_bytes(raw,'little')
        if val<({253:253,254:65536,255:4294967296}[n]):raise ValueError('Noncanonical message PSBT.')
        return val
    result=[]
    for _ in range(3):
        row={}
        while True:
            n=number()
            if not n:break
            if n>128:raise ValueError('Oversized message PSBT key.')
            key=stream.read(n);size=number();value=stream.read(size)
            if size>MAX or len(key)!=n or len(value)!=size or key in row:raise ValueError('Malformed message PSBT field.')
            row[key]=value
        result.append(row)
    if stream.read(1):raise ValueError('Message proof has extra input/output maps.')
    return result

def challenge(address,message,height=None):
    if not isinstance(message,str) or not message or len(message.encode('utf-8'))>65536:raise ValueError('Enter an exact non-empty message of at most 65,536 UTF-8 bytes.')
    spk=script.address_to_scriptpubkey(address);tag=hashlib.sha256(b'BIP0322-signed-message').digest();h=hashlib.sha256(tag+tag+message.encode()).digest()
    spend=Transaction(version=0,vin=[TransactionInput(bytes(32),0xffffffff,script_sig=script.Script(b'\x00\x20'+h),sequence=0)],vout=[TransactionOutput(0,spk)],locktime=0)
    sign=Transaction(version=2 if height else 0,vin=[TransactionInput(spend.txid(),0,sequence=0)],vout=[TransactionOutput(0,script.Script(b'\x6a'))],locktime=height or 0)
    payload=b'psbt\xff'+field(b'\x00',sign.serialize())+b'\x00'+field(b'\x00',spend.serialize())+field(b'\x01',spend.vout[0].serialize())+b'\x00\x00'
    return spend,sign,base64.b64encode(payload).decode()

def check_packet(core,psbt,spend,tx,descriptor):
    g,i,o=maps(psbt)
    if g!={b'\x00':tx.serialize()} or o:raise ValueError('The imported message proof changes the fixed virtual transaction.')
    if b'\x00' in i and i[b'\x00']!=spend.serialize() or b'\x01' in i and i[b'\x01']!=spend.vout[0].serialize():raise ValueError('Message proof contains a different previous output.')
    if b'\x00' not in i and b'\x01' not in i:raise ValueError('Message proof lacks its synthetic previous output.')
    if b'\x03' in i and i[b'\x03'] not in (b'\x01\0\0\0',b'\0\0\0\0' if descriptor.is_taproot else b'\x01\0\0\0'):raise ValueError('Message proofs require ALL or Taproot DEFAULT signatures.')
    for code,wanted in [(b'\x04',descriptor.redeem_script()),(b'\x05',descriptor.witness_script())]:
        if code in i and (wanted is None or i[code]!=wanted.data):raise ValueError('Message proof script differs from the locally verified address policy.')
    decoded=rpc(core,'decodepsbt',[psbt]);scope=decoded['inputs'][0]
    if any(scope.get(k) for k in ('final_scriptSig','final_scriptwitness','taproot_script_path_sigs')):raise ValueError('Import an unfinished message PSBT, not an opaque final witness or unsupported script-path proof.')
    allowed={k.get_public_key().sec() for k in descriptor.keys};count=0
    for pub,sig in scope.get('partial_signatures',{}).items():
        key=bytes.fromhex(pub);signature=bytes.fromhex(sig)
        if key not in allowed or not verify_ecdsa(tx,descriptor,key,signature):raise ValueError('Invalid or unrelated message signature.')
        count+=1
    sig=scope.get('taproot_key_path_sig')
    if sig:
        if not descriptor.is_taproot or not verify_taproot(tx,descriptor,bytes.fromhex(sig)):raise ValueError('Invalid Taproot message signature.')
        count=1
    return count

def verify_ecdsa(tx,d,pub,sig):
    try:
        if len(sig)<9 or sig[-1]!=1:return False
        r,s=decode_dss_signature(sig[:-1])
        if not 0<r<ORDER or not 0<s<=ORDER//2:return False
        witness=d.witness_script()
        code=witness or script.p2pkh(ec.PublicKey.parse(pub))
        h=tx.sighash_segwit(0,code,0,1) if d.is_segwit else tx.sighash_legacy(0,code,1)
        return ec.PublicKey.parse(pub).verify(ec.Signature.parse(sig[:-1]),h)
    except Exception:return False

def verify_taproot(tx,d,sig):
    try:
        if len(sig)==64:flag=0
        elif len(sig)==65 and sig[-1]==1:flag=1
        else:return False
        key=ec.PublicKey.from_xonly(d.script_pubkey().data[2:]);h=tx.sighash_taproot(0,[d.script_pubkey()],[0],sighash=flag)
        return key.schnorr_verify(ec.SchnorrSig(sig[:64]),h)
    except Exception:return False

def verify_final(raw,expected,d,threshold):
    tx=Transaction.parse(bytes.fromhex(raw));clean=Transaction(version=tx.version,vin=[TransactionInput(x.txid,x.vout,sequence=x.sequence) for x in tx.vin],vout=tx.vout,locktime=tx.locktime)
    if clean.serialize()!=expected.serialize():raise ValueError('Final message proof changes its synthetic transaction.')
    vin=tx.vin[0];witness=vin.witness.items;redeem=d.redeem_script();wanted=script.Script(bytes([len(redeem.data)])+redeem.data) if redeem else script.Script(b'')
    if d.is_segwit and vin.script_sig.data!=wanted.data:raise ValueError('Invalid message scriptSig.')
    if d.is_taproot:
        if len(witness)!=1 or not verify_taproot(expected,d,witness[0]):raise ValueError('Final Taproot proof failed independent verification.')
    elif d.witness_script():
        if not witness or witness[-1]!=d.witness_script().data:raise ValueError('Final witness does not match the local policy.')
        sigs=witness[:-1];keys=[k.get_public_key().sec() for k in d.keys]
        multi=len(keys)>1
        if 'sortedmulti(' in str(d):keys.sort()
        if multi:
            if not sigs or sigs[0]!=b'':raise ValueError('Invalid multisig dummy value.')
            sigs=sigs[1:]
        if len(sigs)!=threshold:raise ValueError('Incomplete message signature threshold.')
        cursor=0
        for sig in sigs:
            while cursor<len(keys) and not verify_ecdsa(expected,d,keys[cursor],sig):cursor+=1
            if cursor==len(keys):raise ValueError('Multisig proof failed independent signature verification.')
            cursor+=1
    elif d.is_segwit:
        if len(witness)!=2 or script.p2wpkh(ec.PublicKey.parse(witness[1])).data!=(redeem.data if redeem else d.script_pubkey().data) or not verify_ecdsa(expected,d,witness[1],witness[0]):raise ValueError('Final SegWit proof failed independent verification.')
    else:raise ValueError('This message signer supports SegWit and single-key Taproot addresses. Use an eligible address.')
    return tx

class Messages:
    def __init__(self,core,store,secret):self.core=core;self.store=store;self.secret=secret;self.prepared={}
    def wallets(self):
        return [{'name':name,'disc':name.startswith('Disc ')} for name in rpc(self.core,'listwallets') if rpc(self.core,'getwalletinfo',[],name).get('private_keys_enabled')]
    def prepare(self,wallets,address,message,partial=''):
        if not isinstance(wallets,list) or not 1<=len(wallets)<=15 or len(set(wallets))!=len(wallets) or not set(wallets)<={w['name'] for w in self.wallets()}:raise ValueError('Select one or more available private signing accounts.')
        address=address.strip();spk=script.address_to_scriptpubkey(address);chain=rpc(self.core,'getblockchaininfo')['chain'];info=None;eligible=set()
        for name in rpc(self.core,'listwallets'):
            facts=rpc(self.core,'getaddressinfo',[address],name)
            if facts.get('ismine') or facts.get('iswatchonly'):
                if facts.get('desc'):info=facts
                if name in wallets:eligible.add(name)
        for p in matches(self.core,self.store,address):
            if not p['setup_ready']:raise ValueError('The local wallet policy is still pending setup completion.')
            eligible.update(p['wallets'])
        if not info or not set(wallets)<=eligible:raise ValueError('Selected accounts do not locally control the entered address. Load its public policy/address history first.')
        d=Descriptor.from_string(info['desc']);parsed=restricted(str(d));height=parsed['height'] if parsed else None;threshold=parsed['threshold'] if parsed else 1
        if d.script_pubkey().data!=spk.data or (not parsed and not (str(d).startswith(('sh(wpkh(','tr(')) and len(d.keys)==1 and '{' not in str(d))):raise ValueError('Unsupported or mismatching message policy. Arbitrary scripts and Taproot script trees are refused.')
        spend,tx,psbt=challenge(address,message,height)
        if partial:check_packet(self.core,partial,spend,tx,d);psbt=partial
        for name in rpc(self.core,'listwallets'):
            own=rpc(self.core,'getaddressinfo',[address],name)
            if own.get('ismine') or own.get('iswatchonly'):psbt=rpc(self.core,'walletprocesspsbt',{'psbt':psbt,'sign':False,'bip32derivs':True,'finalize':False},name)['psbt']
        count=check_packet(self.core,psbt,spend,tx,d);key=__import__('secrets').token_hex(16)
        self.prepared={k:v for k,v in self.prepared.items() if time.time()-v['created']<600}
        if len(self.prepared)>=16:raise ValueError('Too many message reviews. Finish or wait for expiry.')
        self.prepared[key]={'wallets':wallets,'address':address,'message':message,'chain':chain,'height':height,'threshold':threshold,'descriptor':d,'spend':spend,'tx':tx,'psbt':psbt,'created':time.time()}
        return {'id':key,'wallets':wallets,'address':address,'message':message,'threshold':threshold,'signatures_present':count,'height':height,'policy':str(d),'notice':'BIP-322 message proof only. No real funds are selected or broadcast. A partial PSBT is not a completed signature.'}
    def sign(self,key):
        p=self.prepared.pop(key,None)
        if not p or time.time()-p['created']>600:raise ValueError('Review the exact message and signing accounts again.')
        if rpc(self.core,'getblockchaininfo')['chain']!=p['chain']:raise ValueError('Node network changed. Review again.')
        psbt=p['psbt'];check_packet(self.core,psbt,p['spend'],p['tx'],p['descriptor'])
        for name in p['wallets']:
            info=rpc(self.core,'getwalletinfo',[],name);password=None
            try:
                if 'unlocked_until' in info:password=self.secret('Bitcoin Core wallet passphrase · sign the reviewed message\nCore wallet: '+__import__('json').dumps(info['walletname'],ensure_ascii=False)+'\nLocal signing account: '+__import__('json').dumps(name,ensure_ascii=False));rpc(self.core,'walletpassphrase',[password,30],name)
                psbt=rpc(self.core,'walletprocesspsbt',{'psbt':psbt,'sign':True,'bip32derivs':True,'finalize':False,'sighashtype':'DEFAULT' if p['descriptor'].is_taproot else 'ALL'},name)['psbt']
            finally:
                password=None
                if 'unlocked_until' in info:rpc(self.core,'walletlock',[],name)
        count=check_packet(self.core,psbt,p['spend'],p['tx'],p['descriptor']);final=rpc(self.core,'finalizepsbt',[psbt])
        if not final.get('complete'):return {'complete':False,'psbt':psbt,'signatures_present':count,'required':p['threshold'],'message':'Partial message proof. Add signatures from other distinct cosigners; do not present this as a completed signature.'}
        tx=verify_final(final['hex'],p['tx'],p['descriptor'],p['threshold']);simple=p['height'] is None and p['descriptor'].redeem_script() is None
        proof=('smp'+base64.b64encode(tx.vin[0].witness.serialize()).decode()) if simple else ('ful'+base64.b64encode(tx.serialize()).decode())
        return {'complete':True,'signature':proof,'format':'BIP-322 simple' if simple else 'BIP-322 full','address':p['address'],'message':p['message'],'height':p['height'],'required':p['threshold'],'notice':'Independently verified message proof. No transaction was broadcast. Your verifier must support BIP-322'+(' and its block-height condition.' if p['height'] else '.')}
