"""Validated block catch-up over the already authorised direct SSH stream."""
import hashlib,time
from wallet_ops import rpc
MAX_BLOCK=4*1024*1024


def publish(store,**facts):
    with store.edit() as s:s.setdefault('chain_sync',{}).update(facts)


def send(core,stream,read,write,progressive=False):
    tip=rpc(core,'getblockchaininfo')
    if not progressive and (tip.get('initialblockdownload') or tip['blocks']!=tip['headers']):raise ValueError('For a source still downloading, use the separate Blockchain over direct SSH controls. Wallet transfer requires the source to finish catching up.')
    offer={'operation':'chain_sync','version':2 if progressive else 1,'chain':tip['chain'],'height':tip['blocks'],'hash':tip['bestblockhash']}
    if progressive:offer.update(source_syncing=bool(tip.get('initialblockdownload') or tip['blocks']<tip['headers']),source_headers=tip['headers'])
    write(stream,offer)
    peer=read(stream)
    if peer.get('status')!='chain_state' or peer.get('chain')!=tip['chain'] or type(peer.get('height')) is not int or not 0<=peer['height']<=2**31:raise ValueError('Receiver did not accept direct Core catch-up.')
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
    fields={'operation','version','chain','height','hash'}
    if hello.get('version')==2:
        fields|={'source_syncing','source_headers'}
        if type(hello.get('source_syncing')) is not bool or type(hello.get('source_headers')) is not int or hello['source_headers']<hello.get('height',0):raise ValueError('Invalid source download state.')
    if set(hello)!=fields or hello.get('operation')!='chain_sync' or type(hello['version']) is not int or hello['version'] not in (1,2) or type(hello['height']) is not int or not 0<=hello['height']<=2**31 or not isinstance(hello['hash'],str) or len(hello['hash'])!=64:raise ValueError('Invalid direct Core catch-up offer.')
    chain=rpc(core,'getblockchaininfo')
    if chain['chain']!=hello['chain']:raise ValueError('Direct Core catch-up uses a different network.')
    saved=store.read().get('chain_sync',{})
    old=saved.get('network_was_active',False) if saved.get('network_paused') else rpc(core,'getnetworkinfo')['networkactive']
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
        actual=rpc(core,'getblockchaininfo')
        publish(store,state='caught_up',current_height=actual['blocks'],source_height=hello['height'],source_syncing=hello.get('source_syncing'),source_headers=hello.get('source_headers'),message='Available source blocks checked. Existing receiver blocks were retained. This does not claim that either node has reached the current network tip.')
        write(stream,{'status':'chain_complete','height':hello['height'],'hash':hello['hash']})
    except Exception:
        publish(store,state='interrupted',message='SSH catch-up interrupted. Core Internet peers remain paused; verified blocks were retained. Reconnect to resume or explicitly resume Internet connections.')
        raise


def finish(core,store):
    state=store.read().get('chain_sync',{})
    if state.get('network_paused') and state.get('state')=='caught_up':
        if state.get('mode')=='ssh_only':
            publish(store,state='waiting_source',message='Available source blocks checked. SSH-only mode keeps Internet peers paused; the source may still be downloading.')
            return
        if state.get('network_was_active'):rpc(core,'setnetworkactive',[True])
        publish(store,network_paused=False,state='complete',message='SSH catch-up complete. The previous Core peer-connection setting was restored.')


def resume_network(core,store):
    saved=store.read()
    if saved.get('active_transfer') or saved.get('sync_batch'):raise ValueError('End the active SSH synchronisation before resuming Internet peers.')
    if saved.get('block_download',{}).get('running'):raise ValueError('Stop direct block receiving before resuming Internet peers.')
    recovery=saved.get('recovery',{})
    if recovery.get('plan',{}).get('replay') and not recovery.get('replay_ready') and recovery.get('state') in ('starting','stopping','downloading','rescanning'):raise ValueError('Wait until recovery wallets are registered before resuming Internet peers.')
    publish(store,mode='internet',network_paused=False,state='internet_resumed',message='Core Internet peer connections resumed by local user.')
    try:rpc(core,'setnetworkactive',[True])
    except Exception:
        publish(store,mode='ssh_only',network_paused=True,state='interrupted',message='Core did not confirm Internet resumption. SSH-only mode retained.');raise
    with store.edit() as state:state.setdefault('block_download',{})['prepared']=False
    return {'ok':True}
