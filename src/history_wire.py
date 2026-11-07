"""Bounded public Core history on the authenticated Agent-to-Agent SSH channel."""
import hashlib,json,tempfile
from pathlib import Path
from wallet_ops import rpc
from approval_store import digest
from wallet_labels import fixed_address
from core_history import MAX_BYTES,collect,validate_rows
NAMESPACE='wallaby-core-history-v1'


def export(core,store,p,details,folder):
    from peer_wallet import source_wallet
    name=source_wallet(core,p);wanted={fixed_address(r['desc']) for r in p['public_wallet']['descriptors']}
    if None in wanted:raise ValueError('Extinct history contains a non-fixed policy.')
    alltx={};offset=0
    while True:
        page=rpc(core,'listtransactions',['*',1000,offset,True],name);offset+=len(page)
        for row in page:
            txid=row['txid']
            if txid in alltx:continue
            tx=rpc(core,'gettransaction',[txid,True],name)
            if tx.get('confirmations',0)<=0:raise ValueError('Extinct source contains unconfirmed history. Wait for confirmation before synchronising.')
            alltx[txid]=(tx,rpc(core,'decoderawtransaction',[tx['hex']]))
        if len(page)<1000:break
        if offset>100000:raise ValueError('Extinct history exceeds one transfer’s bounded record count.')
    own={(txid,o['n']) for txid,(tx,decoded) in alltx.items() for o in decoded['vout'] if o['scriptPubKey'].get('address') in wanted}
    ids={txid for txid,(tx,decoded) in alltx.items() if any((txid,o['n']) in own for o in decoded['vout']) or any((i.get('txid'),i.get('vout')) in own for i in decoded['vin'])}
    labels={r['address']:r['label'] for r in details['address_labels']}
    if not wanted<=labels.keys():raise ValueError('Source Extinct labels are incomplete.')
    manifest={'addresses':[{'address':a,'label':labels[a]} for a in sorted(wanted)],'transactions':[{'txid':i,'blockhash':alltx[i][0]['blockhash']} for i in sorted(ids)]}
    rows=collect(core,[name],ids,folder);validate_rows(core,rows,manifest)
    packet={'version':1,'public_identity':digest(sorted(__import__('build8_policy').descriptors(p['public_wallet']))),'manifest':manifest,'records':rows}
    raw=json.dumps(packet,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>MAX_BYTES:raise ValueError('Public historical records exceed one transfer’s limit.')
    file=Path(folder)/'history.json';file.write_bytes(raw);file.chmod(0o600)
    from setup_messages import sign
    message={'version':1,'kind':'core_history','transfer_id':p['transfer_id'],'details_hash':digest(details),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    return file,{'operation':'public_wallet','core_history':sign(store,message,namespace=NAMESPACE)}


def receive(core,store,p,details,header,stream,read_exact,folder):
    from setup_messages import verify
    preview=store.read()['transfer_previews'][digest(p)]
    message=verify(store,header['core_history'],preview['public_key'],namespace=NAMESPACE)
    if set(message)!={'version','kind','transfer_id','details_hash','sha256','bytes'} or message['version']!=1 or message['kind']!='core_history' or message['transfer_id']!=p['transfer_id'] or message['details_hash']!=digest(details) or type(message['bytes']) is not int or not 0<message['bytes']<=MAX_BYTES:raise ValueError('Historical transfer does not match the signed live preview.')
    # Keep files in the same protected RAM staging area as encrypted sync files.
    path=Path(folder)/'received-history.json';hasher=hashlib.sha256();remaining=message['bytes']
    with path.open('wb') as f:
        path.chmod(0o600)
        while remaining:
            block=read_exact(stream,min(65536,remaining));f.write(block);hasher.update(block);remaining-=len(block)
    if hasher.hexdigest()!=message['sha256']:raise ValueError('Public history checksum mismatch. No archive was updated.')
    packet=json.loads(path.read_text())
    if not isinstance(packet,dict) or set(packet)!={'version','public_identity','manifest','records'} or packet['version']!=1 or packet['public_identity']!=digest(sorted(__import__('build8_policy').descriptors(p['public_wallet']))):raise ValueError('Public historical policy identity differs from the authorised archive.')
    from retirement_phases import manifest
    manifest(packet['manifest'])
    wanted={fixed_address(r['desc']) for r in p['public_wallet']['descriptors']};labels={r['address']:r['label'] for r in details['address_labels']}
    if {r['address']:r['label'] for r in packet['manifest']['addresses']}!={a:labels[a] for a in wanted}:raise ValueError('Historical ownership or LOST labels differ from the signed preview.')
    validate_rows(core,packet['records'],packet['manifest']);return packet
