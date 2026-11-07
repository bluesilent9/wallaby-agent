"""Validated block catch-up over the already authorised direct SSH stream."""
import hashlib,time
from wallet_ops import rpc
MAX_BLOCK=4*1024*1024


def publish(store,**facts):
    with store.edit() as s:s.setdefault('chain_sync',{}).update(facts)


def send(core,stream,read,write):
    tip=rpc(core,'getblockchaininfo')
    if tip.get('initialblockdownload') or tip['blocks']!=tip['headers']:raise ValueError('The sending Core must finish catching up before it can update another node.')
    write(stream,{'operation':'chain_sync','version':1,'chain':tip['chain'],'height':tip['blocks'],'hash':tip['bestblockhash']})
    peer=read(stream)
    if peer.get('status')!='chain_state' or peer.get('chain')!=tip['chain'] or type(peer.get('height')) is not int:raise ValueError('Receiver did not accept direct Core catch-up.')
    def peer_hash(height):
        write(stream,{'operation':'chain_hash','height':height});r=read(stream)
        if r.get('height')!=height or not isinstance(r.get('hash'),str):raise ValueError('Invalid receiver chain locator.')
        return r['hash']
    if peer_hash(0)!=rpc(core,'getblockhash',[0]):raise ValueError('The paired Core nodes use different genesis blocks.')
    low=0;high=min(peer['height'],tip['blocks'])
    while low<high:
        mid=(low+high+1)//2
        if peer_hash(mid)==rpc(core,'getblockhash',[mid]):low=mid
        else:high=mid-1
    start=low+1
    if tip.get('pruned') and start<tip.get('pruneheight',0) and start<=tip['blocks']:raise ValueError('The sending node has pruned blocks needed by the receiver. No Internet fallback was started; use a sender retaining the missing range.')
    write(stream,{'operation':'chain_plan','start':start,'height':tip['blocks'],'hash':tip['bestblockhash']})
    if read(stream).get('status')!='chain_ready':raise ValueError('Receiver refused the Core catch-up range.')
    for height in range(start,tip['blocks']+1):
        block=rpc(core,'getblockhash',[height]);raw=bytes.fromhex(rpc(core,'getblock',[block,0],timeout=60))
        if not 80<=len(raw)<=MAX_BLOCK:raise ValueError('Source returned an invalid block size.')
        write(stream,{'operation':'chain_block','height':height,'hash':block,'bytes':len(raw)});
        view=memoryview(raw)
        while view:
            count=stream.write(view)
            if not count:raise ValueError('SSH block stream ended early.')
            view=view[count:]
        stream.flush()
        reply=read(stream)
        if reply!={'status':'chain_block_ok','height':height,'hash':block}:raise ValueError('Receiving Core did not validate the transferred block.')
    # A source reorg during transfer invalidates the frozen receipt.
    if rpc(core,'getblockhash',[tip['blocks']])!=tip['bestblockhash']:raise ValueError('The sending chain changed during catch-up. Reconnect to reconcile; no Internet fallback was started.')
    write(stream,{'operation':'chain_end','height':tip['blocks'],'hash':tip['bestblockhash']})
    receipt=read(stream)
    if receipt!={'status':'chain_complete','height':tip['blocks'],'hash':tip['bestblockhash']}:raise ValueError('Receiver did not confirm the validated sending-node tip.')
    return receipt


def receive(core,store,stream,hello,read,write,read_exact):
    if set(hello)!={'operation','version','chain','height','hash'} or hello['version']!=1 or type(hello['height']) is not int or not 0<=hello['height']<=2**31 or not isinstance(hello['hash'],str) or len(hello['hash'])!=64:raise ValueError('Invalid direct Core catch-up offer.')
    chain=rpc(core,'getblockchaininfo')
    if chain['chain']!=hello['chain']:raise ValueError('Direct Core catch-up uses a different network.')
    old=rpc(core,'getnetworkinfo')['networkactive']
    rpc(core,'setnetworkactive',[False]);publish(store,state='receiving',network_paused=True,network_was_active=old,current_height=chain['blocks'],target_height=hello['height'],message='Core peer connections paused. Receiving validated blocks over SSH only.')
    try:
        write(stream,{'status':'chain_state','chain':chain['chain'],'height':chain['blocks'],'hash':chain['bestblockhash']})
        for _ in range(64):
            frame=read(stream)
            if frame.get('operation')!='chain_hash':break
            height=frame.get('height')
            if set(frame)!={'operation','height'} or type(height) is not int or not 0<=height<=chain['blocks']:raise ValueError('Invalid receiver chain locator height.')
            write(stream,{'height':height,'hash':rpc(core,'getblockhash',[height])})
        else:raise ValueError('Too many chain locator requests.')
        if set(frame)!={'operation','start','height','hash'} or frame['operation']!='chain_plan' or frame['height']!=hello['height'] or frame['hash']!=hello['hash'] or type(frame['start']) is not int or not 1<=frame['start']<=min(chain['blocks'],hello['height'])+1:raise ValueError('Invalid Core catch-up range.')
        start=frame['start'];write(stream,{'status':'chain_ready'})
        for height in range(start,hello['height']+1):
            row=read(stream)
            if set(row)!={'operation','height','hash','bytes'} or row['operation']!='chain_block' or row['height']!=height or type(row['bytes']) is not int or not 80<=row['bytes']<=MAX_BLOCK:raise ValueError('Invalid block stream frame.')
            raw=read_exact(stream,row['bytes']);block=hashlib.sha256(hashlib.sha256(raw[:80]).digest()).digest()[::-1].hex()
            if block!=row['hash']:raise ValueError('Transferred block bytes do not match their header hash.')
            result=rpc(core,'submitblock',[raw.hex()],timeout=120)
            if result not in (None,'duplicate'):raise ValueError('Core rejected a transferred block. Catch-up stopped; Internet remains paused.')
            header=rpc(core,'getblockheader',[block])
            if header.get('height')!=height:raise ValueError('Transferred block height differs from its header. Internet remains paused.')
            if height%25==0 or height==hello['height']:publish(store,current_height=height,message='Validating SSH blocks: '+format(height,',')+' / '+format(hello['height'],','))
            write(stream,{'status':'chain_block_ok','height':height,'hash':block})
        end=read(stream)
        if end!={'operation':'chain_end','height':hello['height'],'hash':hello['hash']} or rpc(core,'getblockhash',[hello['height']])!=hello['hash']:raise ValueError('Core did not reach the agreed sender tip.')
        rpc(core,'syncwithvalidationinterfacequeue',[],timeout=120)
        for name in rpc(core,'listwallets'):
            info=rpc(core,'getwalletinfo',[],name)
            if info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<hello['height']:raise ValueError('A local wallet has not processed the transferred chain. Internet remains paused.')
        publish(store,state='caught_up',current_height=hello['height'],message='Core reached the sending node’s verified tip. Internet peers remain paused until the SSH transfer completes.')
        write(stream,{'status':'chain_complete','height':hello['height'],'hash':hello['hash']})
    except Exception:
        publish(store,state='interrupted',message='SSH catch-up interrupted. Core Internet peers remain paused; verified blocks were retained. Reconnect to resume or explicitly resume Internet connections.')
        raise


def finish(core,store):
    state=store.read().get('chain_sync',{})
    if state.get('network_paused') and state.get('state')=='caught_up':
        if state.get('network_was_active'):rpc(core,'setnetworkactive',[True])
        publish(store,network_paused=False,state='complete',message='SSH catch-up complete. The previous Core peer-connection setting was restored.')


def resume_network(core,store):
    saved=store.read()
    if saved.get('active_transfer') or saved.get('sync_batch'):raise ValueError('End the active SSH synchronisation before resuming Internet peers.')
    rpc(core,'setnetworkactive',[True]);publish(store,network_paused=False,state='internet_resumed',message='Core Internet peer connections resumed by local user.')
    return {'ok':True}
