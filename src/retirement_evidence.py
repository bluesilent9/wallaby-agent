"""All-record local comparison with bounded examples for separate deletion review."""
from wallet_ops import rpc
from approval_store import digest


def samples(rows):
    if len(rows)<=5:return rows
    return [rows[i] for i in sorted({0,len(rows)//4,len(rows)//2,3*len(rows)//4,len(rows)-1})]


def compare(core,p,facts,archives,archive=None):
    archive=archive or p['preservation']['archive_wallet']
    if archive not in archives:
        return {'verified':False,'archive':None,'address_count':0,'transaction_count':0,'address_samples':[],'transaction_samples':[]}
    from retirement_phases import readback,verify_public
    q=dict(p,wallet=archive)
    readback(core,q);verify_public(core,q,transaction_wallet=archive)
    address_rows=[];transaction_rows=[]
    for row in p['manifest']['addresses']:
        address_rows.append({'address':row['address'],'label':row['label'],'matched':True})
    # Compare every transaction, including its raw bytes and active-chain block,
    # against a local original wallet/monitor, not a Server-provided summary.
    for row in p['manifest']['transactions']:
        original=None
        for wallet in facts['local_wallets']:
            try:tx=rpc(core,'gettransaction',[row['txid'],True],wallet)
            except ValueError:continue
            if tx.get('confirmations',0)>0 and tx.get('blockhash')==row['blockhash']:
                original=tx;break
        if original is None:raise ValueError('Original local wallets cannot confirm every preserved transaction. No deletion authorised.')
        copied=rpc(core,'gettransaction',[row['txid'],True],archive)
        if copied.get('hex')!=original.get('hex') or not copied.get('hex') or copied.get('blockhash')!=original.get('blockhash') or copied.get('confirmations',0)<=0:raise ValueError('Extinct and original transaction records differ. No deletion authorised.')
        header=rpc(core,'getblockheader',[row['blockhash']])
        transaction_rows.append({'txid':row['txid'],'blockhash':row['blockhash'],'height':header['height'],'time':header['time'],'matched':True})
    return {'verified':True,'archive':archive,'address_count':len(address_rows),'transaction_count':len(transaction_rows),'manifest_hash':digest(p['manifest']),'address_samples':samples(address_rows),'transaction_samples':samples(transaction_rows)}
