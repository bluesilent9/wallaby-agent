"""Direct, explicitly approved wallet file transfer through system OpenSSH.

Wallet Server carries only public pairing metadata. Passwords exist only in memory
and an owner-only askpass socket. No credentials, files or paths reach Wallet Server.
"""
import base64,contextlib,hashlib,ipaddress,json,os,pwd,re,secrets,shutil,socket,struct,subprocess,sys,tempfile,threading,time
from pathlib import Path
from approval_store import Store,digest
from public_policy import ipv6,descriptors
from wallet_ops import rpc
from ipv6_resolver import resolve as resolve_ipv6
from diagnostics import ConnectionFailure

PORT=22
MAX_FILE=256*1024*1024
MAX_HEADER=1024*1024
LIFETIME=900

def local_ipv6(host=None):
    from configuration import Config
    host=host or Config().values.get('hostname')
    if not host:return None
    try:
        try:addresses=[(ipv6(host),22,0,0)]
        except ValueError:addresses=resolve_ipv6(host,22,timeout=2)
        for address in addresses:
            with socket.socket(socket.AF_INET6,socket.SOCK_DGRAM) as s:
                s.connect(address);return ipv6(s.getsockname()[0])
    except (OSError,ValueError,ConnectionFailure):pass
    return None

def active(store):
    with store.edit() as s:
        key=s.get('active_transfer') or s.get('viewed_transfer')
        if key and key in s['pending'] and (not s['pending'][key].get('withdrawn') or key==s.get('active_transfer')):return key,s['pending'][key]
        candidates=[(k,v) for k,v in s['pending'].items() if v['proposal']['kind']=='wallet_transfer' and v['state']=='pending' and not v.get('withdrawn')]
        if not candidates:s.pop('active_transfer',None);return None,None
        key,row=min(candidates,key=lambda kv:(kv[1]['proposal']['public_wallet']['wallet_name'].casefold(),kv[0]))
        return key,row

def frame_write(stream,value):
    raw=json.dumps(value,allow_nan=False,separators=(',',':')).encode()
    if len(raw)>MAX_HEADER:raise ValueError('Transfer header too large.')
    view=memoryview(struct.pack('!I',len(raw))+raw)
    while view:
        count=stream.write(view)
        if not count:raise ValueError('Direct SSH connection ended while sending a frame.')
        view=view[count:]
    stream.flush()

def read_exact(stream,n):
    data=bytearray()
    while len(data)<n:
        part=stream.read(min(n-len(data),1024*1024))
        if not part:raise ValueError('Direct SSH connection ended before confirmation.')
        data.extend(part)
    return bytes(data)

def frame_read(stream):
    n=struct.unpack('!I',read_exact(stream,4))[0]
    if not 0<n<=MAX_HEADER:raise ValueError('Invalid transfer header length.')
    from node_client import decode
    value=decode(read_exact(stream,n))
    if not isinstance(value,dict):raise ValueError('Invalid transfer message.')
    return value

def socket_path(store):return store.root/'peer.sock'

def host_fingerprints():
    result=[]
    for p in Path('/etc/ssh').glob('ssh_host_*_key.pub'):
        try:
            parts=p.read_text().split();result.append({'type':parts[0],'fingerprint':'SHA256:'+base64.b64encode(hashlib.sha256(base64.b64decode(parts[1],validate=True)).digest()).decode().rstrip('=')})
        except (OSError,ValueError,IndexError):pass
    return result

def readiness(p):
    if p.get('transfer_version')==3:return {'relay':True,'installed':True,'listening':True,'message':'Authenticated encrypted relay; no inbound SSH listener or peer login required.'}
    present=Path('/usr/sbin/sshd').exists();listening=False
    try:listening=bool(subprocess.run(['/usr/bin/ss','-H','-6','-ltn','sport = :22'],capture_output=True,text=True,timeout=3).stdout.strip())
    except OSError:pass
    peer=ipv6(p['peer']['ipv6']);address=local_ipv6()
    return {'installed':present,'listening':listening,'ipv6':address,'username':pwd.getpwuid(os.getuid()).pw_name,'fingerprints':host_fingerprints(),
            'install_command':'sudo apt install openssh-server','start_command':'sudo systemctl start ssh.socket',
            'firewall_check_command':'sudo ufw status verbose','firewall_rule_command':f'sudo ufw allow proto tcp from {peer} to any port 22 comment Wallaby-sync',
            'firewall_remove_command':f'sudo ufw delete allow proto tcp from {peer} to any port 22',
            'network_note':'The receiving SSH server must permit this local account and password authentication. Never enable root login. If UFW is active, its IPv6 support must be enabled (IPV6=yes in /etc/default/ufw). On the receiving modem, allow incoming IPv6 TCP 22 to this computer from the sending IPv6 address. IPv6 normally needs a firewall exception, not IPv4 port forwarding. The Agent cannot reliably inspect your modem or distinguish a modem block from a host firewall or routing failure. System SSH remains controlled by you; closing this transfer closes its direct connection and the Agent receiving socket, not an existing SSH server.'}

def source_wallet(core,p,require_encrypted=False,*,public_preview=False,restoration_permit=None):
    from managed_accounts import guard
    guard(core,p,public_preview=public_preview,restoration_permit=restoration_permit)
    wanted=descriptors(p['public_wallet']);matches=[]
    from extinct_sync import grouped,ARCHIVE
    if grouped(p['public_wallet']) and not p['source_has_private_keys'] and ARCHIVE in rpc(core,'listwallets'):
        raw=rpc(core,'listdescriptors',[False],ARCHIVE);info=rpc(core,'getwalletinfo',[],ARCHIVE)
        if wanted<=descriptors(raw) and not info.get('private_keys_enabled') and not info.get('scanning'):return ARCHIVE
    for name in rpc(core,'listwallets'):
        try:
            raw=rpc(core,'listdescriptors',[False],name)
            from wallet_labels import address_only
            actual=descriptors(raw)
            if actual==wanted or (not p['source_has_private_keys'] and address_only(p['public_wallet']) and wanted<=actual):matches.append(name)
        except ValueError:continue
    if len(matches)>1 and __import__('signer_restoration').requested(p):matches=[n for n in matches if n==p['public_wallet']['wallet_name']]
    if len(matches)!=1:raise ValueError('The local public descriptors must identify exactly one loaded source wallet. Load the wallet and resolve duplicate replicas first.')
    guard(core,p,actual_name=matches[0],public_preview=public_preview,restoration_permit=restoration_permit)
    info=rpc(core,'getwalletinfo',[],matches[0])
    if info.get('private_keys_enabled')!=p['source_has_private_keys'] or info.get('scanning'):raise ValueError('Source wallet key capability changed or its scan is incomplete.')
    if require_encrypted and info.get('wallaby_storage')=='disc':raise ValueError('A physical-only disc signer cannot be copied into a persistent node wallet. Use its verified physical backup/recovery workflow; no private wallet file was sent.')
    if require_encrypted and info.get('private_keys_enabled') and ('unlocked_until' not in info or info['unlocked_until']!=0):raise ValueError('Lock this encrypted wallet in Bitcoin Core before sending. Unencrypted private-key wallets cannot be transferred; encrypt and back up the wallet in Core first.')
    return matches[0]

def wallet_details(core,p,store=None,local_source=None):
    """Funded address facts originate at Core, transferred peer-to-peer, never asserted by Wallet Server."""
    if local_source is None and __import__('extinct_sync').grouped(p['public_wallet']):return __import__('extinct_sync').local_details(core,p,store)
    name=local_source if local_source is not None else source_wallet(core,p,public_preview=True)
    if local_source is not None:
        raw=rpc(core,'listdescriptors',[False],name);info=rpc(core,'getwalletinfo',[],name)
        if info.get('private_keys_enabled') or p['source_has_private_keys'] or info.get('scanning') or not descriptors(p['public_wallet'])<=descriptors(raw):raise ValueError('Local historical source differs from the reviewed public addresses.')
    names=[name];vaults=[]
    if p.get('transfer_version') in (2,3):
        from wallet_ops import verify_vault
        from vault_policy import public_vault
        for item in (store or Store()).read()['vaults'].values():
            v=public_vault(item['public'])
            if descriptors({'wallet_name':'vault','descriptors':[{'desc':v['source']['descriptor']}]}) <= descriptors(p['public_wallet']):
                verify_vault(core,v);vaults.append(v)
                monitor=item.get('monitor_wallet')
                if monitor and monitor in rpc(core,'listwallets'):names.append(monitor)
    current={};coin_wallet={};transactions={}
    for wallet in names:
        history=rpc(core,'listsinceblock',[],wallet).get('transactions',[])
        if len(history)>100000:raise ValueError('Wallet history exceeds the safe review limit.')
        # Core's receive/send summaries omit change, and listunspent omits locked
        # outputs. Inspect all outputs of locally known transactions instead.
        for txid in {tx['txid'] for tx in history}:
            tx=rpc(core,'gettransaction',[txid,True],wallet);transactions[(wallet,txid)]=tx
            decoded=rpc(core,'decoderawtransaction',[tx['hex']])
            for output in decoded['vout']:
                address=output['scriptPubKey'].get('address')
                if not address:continue
                info=rpc(core,'getaddressinfo',[address],wallet)
                if not (info.get('ismine') or info.get('iswatchonly')):continue
                key=(txid,output['n'])
                if key in current:continue
                coin=rpc(core,'gettxout',[key[0],key[1],True])
                if coin and __import__('wallet_ops').sats(coin['value'])>0:
                    current[key]={'txid':key[0],'vout':key[1],'amount':coin['value'],'address':address,'confirmations':coin.get('confirmations',0)};coin_wallet[key]=wallet
    utxos=list(current.values());rows=[];heights={}
    if len(utxos)>10000:raise ValueError('Wallet has too many funded outputs for one review.')
    for u in utxos:
        tx=transactions[(coin_wallet[(u['txid'],u['vout'])],u['txid'])];height=None
        if tx.get('blockhash'):
            h=tx['blockhash']
            if h not in heights:heights[h]=rpc(core,'getblockheader',[h])['height']
            height=heights[h]
        rows.append({'address':u.get('address','Unknown script'),'txid':u['txid'],'vout':u['vout'],'amount_sats':str(__import__('wallet_ops').sats(u['amount'])),'time_received':tx.get('timereceived',tx.get('time')),'blockheight':height,'confirmations':u.get('confirmations',0)})
    raw=rpc(core,'listdescriptors',[False],name)
    if p.get('transfer_version') in (2,3):
        from wallet_labels import address_only,fixed_address,read_labels
        if address_only(p['public_wallet']):
            wanted=descriptors(p['public_wallet']);raw['descriptors']=[r for r in raw['descriptors'] if descriptors({'wallet_name':name,'descriptors':[r]})<=wanted]
            addresses={fixed_address(r['desc']) for r in raw['descriptors']};rows=[row for row in rows if row['address'] in addresses]
        labels=read_labels(core,name,raw,rows)
        if address_only(raw) and not __import__('extinct_sync').grouped(p['public_wallet']):
            groups={r['label'].split(' | LOST:',1)[0].strip() for r in labels if r['label']}
            if len(groups)==1:raw['wallet_name']=next(iter(groups))
    if __import__('extinct_sync').grouped(p['public_wallet']):raw['wallet_name']='Wallaby Extinct'
    result={'public_wallet':raw,'funded_outputs':rows,'chain':rpc(core,'getblockchaininfo')['chain']}
    if p.get('transfer_version') in (2,3):result.update(vaults=vaults,address_labels=labels)
    return result

def work_dir(core):
    from protected_memory import required,root
    if required():
        p=root()/'transfer-files';p.mkdir(mode=0o700,exist_ok=True);return p

    # The Core cookie's parent is accessible to the same Core, including Snap data roots.
    root=Path(core.config['cookie']).expanduser().resolve().parent/'wallaby-transfers';
    if root.is_symlink():raise ValueError('Unsafe transfer staging directory.')
    root.mkdir(mode=0o700,exist_ok=True)
    if root.is_symlink() or root.stat().st_uid!=os.getuid():raise ValueError('Unsafe transfer staging directory.')
    root.chmod(0o700);return root

class Transfer:
    def __init__(self,core,store=None):
        self.core=core;self.store=store or Store();self.lock=threading.Lock();self.listener=None;self.deadline=0;self.thread=None;self.details=None;self.error='';self.success_until=0;self.connection=None;self.manifest_approved=False;self.firewall={'state':'unchecked','message':'The local firewall has not been checked.'}
    def state(self):
        
        key,row=active(self.store)
        if self.listener and not self.connection and time.monotonic()>self.deadline:self.close();self.error='Receiving authorisation expired. Review and authorise again.'
        preview=self.store.read().get('transfer_previews',{}).get(key) if key else None
        proof={}
        self.details=None
        if preview:
            from wallet_preview import fingerprint
            proof={'fingerprint':fingerprint(preview['public_key']),'preview_hash':digest(preview['preview'])}
            self.details={k:preview['preview'][k] for k in ('public_wallet','chain','funded_outputs','vaults','address_labels') if k in preview['preview']}
        from sync_queue import rows
        relay_route=None;relay_progress=None
        if row and row['proposal'].get('transfer_version')==3:
            from peer_mesh import manager
            peers=getattr(self.store,'peers',None)
            try:
                channel=manager(self.store).binding(row['proposal']);peers.direct.require(channel);relay_route={'ready':True,'message':'QR-paired direct SSH ready. Wallet and blockchain bytes bypass Wallet Server.'}
            except ValueError as error:relay_route={'ready':False,'message':str(error)}
            streams=list(getattr(getattr(peers,'wallet_bridge',None),'streams',{}).values())
            relay_progress={'sent_bytes':sum(s.tx for s in streams),'received_bytes':sum(s.rx for s in streams),'paused':bool(peers and time.monotonic()<peers.backpressured_until)}
        return {'relay_progress':relay_progress,'rows':rows(self.store),'batch':self.store.read().get('sync_batch'),'route':(relay_route if row['proposal'].get('transfer_version')==3 else route_info(row['proposal']['peer']['ipv6'])) if row else None,'initial_preview':preview,'preview_proof':proof,'preview_error':self.store.read().get('preview_errors',{}).get(key,''),'id':key,'proposal':row['proposal'] if row else None,'state':row['state'] if row else None,'ready':bool(self.listener),'sending':getattr(self,'sending',False),'firewall':self.firewall,'details':self.details,'error':self.error,'success_until':self.success_until,'setup':readiness(row['proposal']) if row else None,'chain_sync':self.store.read().get('chain_sync',{}),'original_assignments':[{'wallet_name':b['wallet_name'],'binding_id':b['binding_id'],'had_private':b['had_private']} for _,b in __import__('signer_restoration').candidates(self.store.read(),row['proposal']['public_wallet'])] if row and __import__('signer_restoration').requested(row['proposal']) else []}
    def review(self,key):
        with self.store.edit() as s:
            if key not in s['pending'] or s['pending'][key].get('withdrawn') or s['pending'][key]['proposal']['kind']!='wallet_transfer':raise ValueError('Wallet request was withdrawn.')
            s['viewed_transfer']=key
        current,row=active(self.store)
        if key!=current or not row:raise ValueError('This is not the active synchronisation request.')
        if row['state']!='pending':return self.state()
        p=row['proposal']
        from managed_accounts import guard
        guard(self.core,p,self.store,public_preview=True)
        if p['direction']=='send':
            if p.get('preview_challenge'):
                from wallet_preview import prepare
                if key not in self.store.read().get('transfer_previews',{}):prepare(self.core,self.store,key,p)
            else:self.details=wallet_details(self.core,p,self.store)
        else:self.details=None
        return self.state()
    def authorise(self,key,sender_fingerprint):
        with self.lock:
            current,row=active(self.store)
            if key!=current or not row or row['proposal']['direction']!='receive':raise ValueError('Review the active receiving request.')
            from managed_accounts import guard
            guard(self.core,row['proposal'],self.store,public_preview=True)
            from wallet_preview import verify_bound
            payload=self.store.read().get('transfer_previews',{}).get(key)
            if not row['proposal'].get('preview_challenge') or not payload:raise ValueError('The initial node-verified wallet preview is missing. Wallet Server Build 8 needs the documented preview protocol update; receiving is disabled until then.')
            if row['proposal'].get('transfer_version')!=3:raise ValueError('Reconnect the paired Agents and request a current direct wallet sync. Manual identity entry is no longer supported.')
            proof=verify_bound(self.store,payload,row['proposal'])
            if row['proposal'].get('transfer_version')==3:
                from peer_mesh import manager
                c=manager(self.store).binding(row['proposal']);manager(self.store).direct.require(c);sender_fingerprint=__import__('wallet_preview').fingerprint(c.peer['identity_key'])
            if sender_fingerprint!=proof['fingerprint']:raise ValueError('The signed preview differs from the authenticated direct Agent identity. No transfer was authorised.')
            if row['state']!='pending':raise ValueError('This receiving request was already attempted. Reconcile it before retrying.')
            if not readiness(row['proposal'])['listening']:raise ValueError('Start the receiving machine’s IPv6 SSH listener using the displayed instructions, then Authorise again.')
            if self.thread and self.thread.is_alive():raise ValueError('Receiving is already active. Finish or cancel it first.')
            self.close();self.cancel_requested=False;self.manifest_approved=False;self.error='';path=socket_path(self.store)
            if path.exists():path.unlink()
            self.listener=socket.socket(socket.AF_UNIX);self.listener.bind(str(path));path.chmod(0o600);self.listener.listen(1);self.listener.settimeout(1);self.deadline=time.monotonic()+LIFETIME
            self.thread=threading.Thread(target=self.receive,args=(key,row['proposal']),daemon=True);self.thread.start();return self.state()
    def close(self):
        listener=self.listener;self.listener=None
        if self.connection:
            try:self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            self.connection.close();self.connection=None
        if listener:
            listener.close();socket_path(self.store).unlink(missing_ok=True)
    def complete(self,key):
        self.store.queue('wallet_transfer_result',{'request_hash':key,'status':'complete'})
        with self.store.edit() as s:s['pending'].pop(key,None);s['completed'][key]={'kind':'wallet_transfer','at':time.time()};s.pop('active_transfer',None)
        self.success_until=time.time()+5;self.details=None
    def resume_network(self):
        if self.connection:raise ValueError('Wait for the current SSH transfer before resuming Internet peers.')
        from chain_sync import resume_network
        return resume_network(self.core,self.store)
    def pending_recovery(self,key):
        with self.store.edit() as s:
            s['pending'][key]['state']='recovery_required';s.pop('active_transfer',None)
        self.store.queue('wallet_transfer_result',{'request_hash':key,'status':'recovery_required','message':'Wallet data received; local history recovery and verification are still required.'})
    def cancel(self,key):
        # Never claim a failed/uncertain restore succeeded or automatically replay it.
        current,row=active(self.store)
        if key!=current:raise ValueError('Active request changed.')
        if getattr(self,'sending',False) or (row['state']=='attempted' and self.thread and self.thread.is_alive()):raise ValueError('Wallet transfer/restoration is running. Wait for its result before cancelling.')
        self.close()
        with self.store.edit() as s:s.pop('active_transfer',None)
        self.details=None # The request remains in the Wallet Server-owned list.
    def receive(self,key,p):
        from activity_log import event
        event('sync.receive','Direct receive started · request='+key[:12])
        conn=None;path=None;listener=self.listener
        try:
            if p.get('transfer_version')==3:
                pull=getattr(getattr(self.store,'peers',None),'wallet_pull',None)
                if pull is None:raise ValueError('Update both Agents for receiver-initiated wallet sync.')
                pull.request(key,p)
            listener=self.listener
            while self.listener is listener and time.monotonic()<self.deadline:
                if self.error:raise ValueError(self.error)
                try:conn,_=listener.accept();break
                except socket.timeout:continue
            if conn is None:raise ValueError('The approved source did not open the direct wallet stream before receiving expired. No wallet was installed.')
            uid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
            if uid!=os.getuid():raise ValueError('Incoming SSH account differs from the authorised local user.')
            event('sync.receive','Authenticated wallet stream connected · request='+key[:12])
            self.connection=conn
            conn.settimeout(LIFETIME);stream=conn.makefile('rwb',buffering=0);header=frame_read(stream)
            batch=self.store.read().get('sync_batch')
            if batch and batch['direction']=='receive':
                saved=self.store.read();matches=[(k,saved['pending'][k]) for k in batch['keys'] if k in saved['pending'] and saved['pending'][k]['state']=='pending' and not saved['pending'][k].get('withdrawn') and saved['pending'][k]['proposal']['transfer_id']==header.get('transfer_id')]
                if len(matches)!=1:raise ValueError('This wallet was not locally authorised in the selected batch.')
                key,row=matches[0];p=row['proposal']
                with self.store.edit() as state:state['active_transfer']=key
            from managed_accounts import guard
            guard(self.core,p,self.store,public_preview=True)
            if p.get('transfer_version')==3:
                from peer_mesh import manager
                c=manager(self.store).binding(p)
                if header.get('peer_endpoint')!=c.peer['endpoint_id']:raise ValueError('Encrypted sender differs from approved peer.')
            elif ipv6(header.get('peer_ipv6'))!=ipv6(p['peer']['ipv6']):raise ValueError('Authenticated SSH source differs from request.')
            if header.get('operation')!='manifest' or header.get('transfer_id')!=p['transfer_id']:raise ValueError('Transfer differs from the approved request.')
            details=header.get('details');wanted=descriptors(p['public_wallet'])
            if not isinstance(details,dict) or descriptors(details.get('public_wallet'))!=wanted or details.get('chain')!=rpc(self.core,'getblockchaininfo')['chain']:raise ValueError('Direct peer public wallet does not match the approved descriptors/network.')
            # A second local click approves the actual live peer history, not server-provided claims.
            validate_details(details)
            preview=self.store.read().get('transfer_previews',{}).get(key)
            if not preview or not same_facts(details,{k:preview['preview'][k] for k in ('public_wallet','chain','funded_outputs','vaults','address_labels') if k in preview['preview']}):raise ValueError('Live SSH wallet details differ from the independently verified initial preview. Cancel and start a fresh request.')
            self.details=details
            frame_write(stream,{'status':'review_required'})
            option=self.store.read().get('sync_batch',{}).get('options',{}).get(key,{})
            watch=not p['source_has_private_keys'] or option.get('watch_only',False) or header.get('watch_only',False)
            if type(header.get('watch_only',False)) is not bool:raise ValueError('Invalid watch-only choice.')
            if p.get('transfer_version') not in (2,3) and watch:raise ValueError('Watch-only transfer requires the Build 8 direct protocol on both Agents.')
            from signer_restoration import requested,offer,verify_received,finish as finish_restoration,candidates
            if candidates(self.store.read(),p['public_wallet']) and not requested(p):raise ValueError('This wallet needs a Build 65 restoration invitation and signed restoration preview.')
            restoration_offer=offer(self.store,p,watch)
            ready={'status':'ready','features':['chain_sync_v1','core_history_v1','restore_roles_v1','core_history_v2','core_history_v3','core_history_v4']}
            if restoration_offer:ready['restoration']=restoration_offer
            if p.get('transfer_version') in (2,3):ready['watch_only']=watch
            frame_write(stream,ready)
            header=frame_read(stream)
            native_peer=False
            if header.get('operation')=='chain_sync':
                from chain_sync import receive as receive_chain
                receive_chain(self.core,self.store,stream,header,frame_read,frame_write,read_exact);native_peer=True
                header=frame_read(stream)
            from local_extinction import restoration,restored_from_ssh
            if restoration(self.store,p['public_wallet']) and not native_peer:raise ValueError('Restoring an extinct wallet requires direct SSH synchronisation with a Build 64 sending Agent.')
            if requested(p) and not native_peer:raise ValueError('Original signer restoration requires Core-validated direct SSH catch-up.')
            watch_snapshot=bool(restoration_offer and watch and header.get('operation')=='watch_snapshot')
            if watch and not watch_snapshot:
                if header.get('operation')!='public_wallet' or set(header) not in ({'operation'},{'operation','core_history'}):raise ValueError('Watch-only transfer cannot contain a wallet file.')
                from wallet_recovery import verify_history
                from extinct_sync import import_watch
                if 'core_history' in header:
                    from history_wire import receive as receive_history
                    from core_history import install
                    with tempfile.TemporaryDirectory(dir=work_dir(self.core)) as folder:
                        packet=receive_history(self.core,self.store,p,details,header,stream,read_exact,folder)
                        from wallet_loading import ownership_wallets
                        with ownership_wallets(self.core):
                            if getattr(self,'cancel_requested',False):raise ValueError('Receiving cancelled locally before archive import.')
                            try:
                                from local_extinction import eligible
                                eligible(self.core,self.store,p['public_wallet'],verified_history=packet.get('coverage') if packet['version']>=2 else None)
                            except ValueError as error:
                                frame_write(stream,{'status':'history_deferred','transfer_id':p['transfer_id'],'message':str(error)});frame_read(stream)
                                from chain_sync import finish
                                finish(self.core,self.store);self.error=str(error);return
                            if getattr(self,'cancel_requested',False):raise ValueError('Receiving cancelled locally before archive import.')
                            if packet['version']>=2:
                                from extinct_history_sync import install_packet
                                name=install_packet(self.core,self.store,key,p,details,packet)
                            else:
                                name,missing,details=import_watch(self.core,self.store,key,p,details,native=True)
                                install(self.core,self.store,name,packet['records'],packet['manifest'])
                    from chain_sync import finish
                    self.complete(key);frame_write(stream,{'status':'loaded','transfer_id':p['transfer_id'],'wallet_identity':digest(sorted(wanted))});frame_read(stream);finish(self.core,self.store);return
                name,missing,details=import_watch(self.core,self.store,key,p,details)
                if missing:
                    self.pending_recovery(key)
                    frame_write(stream,{'status':'recovery_required','transfer_id':p['transfer_id']});frame_read(stream);return
                verify_history(self.core,name,details,self.store)
                actual=descriptors(rpc(self.core,'listdescriptors',[False],name))
                with self.store.edit() as state:state.get('history_jobs',{}).pop(key,None)
                if restoration_offer:finish_restoration(self.core,self.store,p,name,restoration_offer['bindings'][0]['binding_id'],restoration_offer)
                else:restored_from_ssh(self.core,self.store,p['public_wallet'],name,validated_ssh=native_peer)
                self.complete(key);frame_write(stream,{'status':'loaded','transfer_id':p['transfer_id'],'wallet_identity':digest(sorted(actual))});frame_read(stream)
                if native_peer:
                    from chain_sync import finish
                    finish(self.core,self.store)
                return
            expected_header={'operation','size','sha256','restoration'} if watch_snapshot else {'size','sha256','restoration'} if restoration_offer else {'size','sha256'}
            if set(header)!=expected_header or type(header['size']) is not int or not 0<header['size']<=MAX_FILE or not re.fullmatch('[0-9a-f]{64}',header['sha256']):raise ValueError('Invalid encrypted wallet file header.')
            # Never overwrite a wallet, even if the server chose an existing name.
            for name in rpc(self.core,'listwallets'):
                local=rpc(self.core,'listdescriptors',[False],name)
                if not local.get('descriptors'):continue
                if descriptors(local) & wanted:
                    if restoration_offer and not watch_snapshot:
                        from signer_restoration import capture
                        existing=capture(self.core,[name])[0]['private_key_ids']
                        if existing and all(existing!=b['private_key_ids'] for b in restoration_offer['bindings']):continue
                    raise FileExistsError('This wallet is already present locally.')
            root=work_dir(self.core);fd,filename=tempfile.mkstemp(prefix='receive-',dir=root);path=Path(filename);hasher=hashlib.sha256();remaining=header['size']
            with os.fdopen(fd,'wb') as out:
                while remaining:
                    chunk=read_exact(stream,min(65536,remaining));out.write(chunk);hasher.update(chunk);remaining-=len(chunk)
                out.flush();os.fsync(out.fileno())
            if hasher.hexdigest()!=header['sha256']:raise ValueError('Wallet file integrity check failed.')
            if watch_snapshot:
                from signer_restoration import backup_keys
                from watch_snapshot import verify as verify_watch_snapshot
                verify_watch_snapshot(path)
                if backup_keys(path)['private_key_ids'] or header['restoration']!={'permit_hash':digest(restoration_offer),'binding_id':restoration_offer['bindings'][0]['binding_id']}:raise ValueError('Watch-only restoration contains private keys or differs from the local SSH permit.')
                restored_binding=restoration_offer['bindings'][0]['binding_id']
            else:restored_binding=verify_received(p,restoration_offer,path,header['restoration']) if restoration_offer else None
            with self.store.edit() as s:s['pending'][key]['state']='attempted'
            name='Wallaby Sync '+p['transfer_id'][:24]
            from wallet_recovery import history_missing,earliest,require
            if p.get('transfer_version') in (2,3) and not native_peer and history_missing(self.core,earliest(details)):
                # Preserve the one received encrypted file for an explicitly approved restore.
                staged=root/('pending-'+p['transfer_id']+'.dat')
                if staged.exists():raise ValueError('An encrypted file for this transfer is already staged. Inspect recovery status.')
                os.rename(path,staged);path=None
                require(self.store,key,name,details,staged);self.pending_recovery(key)
                frame_write(stream,{'status':'recovery_required','transfer_id':p['transfer_id']});frame_read(stream);return
            if any(w['name']==name for w in rpc(self.core,'listwalletdir')['wallets']):raise ValueError('A previous restoration exists. Inspect it in Core; it will not be overwritten.')
            rpc(self.core,'restorewallet',{'wallet_name':name,'backup_file':__import__('core_ram_path').for_core(self.core,path),'load_on_startup':True},timeout=600)
            info=rpc(self.core,'getwalletinfo',[],name);actual=descriptors(rpc(self.core,'listdescriptors',[False],name))
            if actual!=wanted or info.get('private_keys_enabled')!=(False if watch_snapshot else p['source_has_private_keys']) or (info.get('private_keys_enabled') and ('unlocked_until' not in info or info['unlocked_until']!=0)) or info.get('scanning'):
                rpc(self.core,'unloadwallet',{'wallet_name':name,'load_on_startup':False});raise ValueError('Restored wallet failed descriptor, encryption or scan verification; unloaded. Inspect it in Core before retrying.')
            if p.get('transfer_version') in (2,3):
                from wallet_labels import apply_labels
                apply_labels(self.core,name,details.get('address_labels',[]),write=False)
                from wallet_recovery import verify_history
                verify_history(self.core,name,details,self.store)
            for output in ([] if p.get('transfer_version') in (2,3) else details['funded_outputs']):
                coin=rpc(self.core,'gettxout',[output['txid'],output['vout'],True])
                if not coin or str(__import__('wallet_ops').sats(coin['value']))!=output['amount_sats'] or coin['scriptPubKey'].get('address')!=output['address']:
                    raise ValueError('A funded output is missing or changed on the receiving node. Check blockchain synchronisation and wallet history before retrying; success was not recorded.')
                rpc(self.core,'gettransaction',[output['txid'],True],name)
            if restoration_offer:finish_restoration(self.core,self.store,p,name,restored_binding,restoration_offer)
            else:restored_from_ssh(self.core,self.store,p['public_wallet'],name,validated_ssh=native_peer)
            self.complete(key);frame_write(stream,{'status':'loaded','transfer_id':p['transfer_id'],'wallet_identity':digest(sorted(actual))})
            # Sender explicitly confirms learning the receiver loaded successfully.
            frame_read(stream)
            if native_peer:
                from chain_sync import finish
                finish(self.core,self.store)
        except Exception as e:
            if p.get('transfer_version')==3:
                saved=self.store.read()['pending'].get(key)
                if saved and saved['state']=='attempted':self.pending_recovery(key)
            self.error='Receiving cancelled locally. Completed wallet work was retained; no transfer was retried.' if getattr(self,'cancel_requested',False) else str(e) if isinstance(e,(ValueError,FileExistsError)) else 'Direct transfer failed or its outcome is uncertain. Inspect Core before retrying.'
            event('sync.receive','Stopped · request='+key[:12]+' · exception='+type(e).__name__+' · attempted='+str(bool(saved and saved['state']=='attempted')).lower() if p.get('transfer_version')==3 else 'Stopped · legacy request')
            if conn:
                try:frame_write(conn.makefile('rwb',buffering=0),{'status':'error','message':self.error})
                except OSError:pass
        finally:
            if path:path.unlink(missing_ok=True)
            if conn:conn.close()
            self.connection=None
            if not self.error:self.deadline=time.monotonic()+LIFETIME
            if self.listener is listener and not self.store.read().get('sync_batch'):self.close()
    def send(self,key,username=None,password=None,fingerprint=None):
        row=self.store.read()['pending'].get(key)
        if not row or row['proposal'].get('transfer_version')!=3:
            raise ValueError('Use the paired direct connection and approve Receive on the receiving Agent. Legacy login transfers are unavailable.')
        from relay_transfer import send
        return send(self,key)


def peer_receive(input_stream=None,output_stream=None,ssh_connection=None):
    from protected_memory import required,inside
    if required() and not inside():
        from protected_peer import handoff
        return handoff()
    input_stream=input_stream or sys.stdin.buffer;output_stream=output_stream or sys.stdout.buffer
    # Called as the logged-in SSH user. Relay only; no RPC/file paths accepted here.
    source=(ssh_connection if ssh_connection is not None else os.environ.get('SSH_CONNECTION','')).split()
    if len(source)!=4:raise ValueError('This command is only available through an SSH session.')
    address=ipv6(source[0]);store=Store();saved=store.read();key,row=active(store)
    batch=saved.get('sync_batch')
    authorised=[saved['pending'][k] for k in batch['keys'] if k in saved['pending'] and not saved['pending'][k].get('withdrawn')] if batch and batch['direction']=='receive' else [row] if row else []
    if not any(r['proposal']['direction']=='receive' and ipv6(r['proposal']['peer']['ipv6'])==address for r in authorised):raise ValueError('No locally authorised request for this SSH peer.')
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(LIFETIME);s.connect(str(socket_path(store)))
        # Verify the peer-claimed IP against sshd, then reconstruct the framed header.
        header=frame_read(input_stream)
        if header.get('peer_ipv6')!=address:raise ValueError('SSH source differs from transfer header.')
        remote=s.makefile('rwb',buffering=0);frame_write(remote,header)
        def upload():
            try:
                while True:
                    data=input_stream.read1(65536) if hasattr(input_stream,'read1') else input_stream.read(65536)
                    if not data:break
                    s.sendall(data)
                s.shutdown(socket.SHUT_WR)
            except OSError:pass
        threading.Thread(target=upload,daemon=True).start()
        while True:
            data=s.recv(65536)
            if not data:break
            output_stream.write(data);output_stream.flush()

def askpass():
    path=Path(os.environ['WALLABY_ASKPASS_SOCKET'])
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(30);s.connect(str(path));data=s.recv(4096)
        sys.stdout.buffer.write(data);sys.stdout.buffer.flush()

def validate_details(details):
    if set(details) not in ({'public_wallet','funded_outputs','chain'},{'public_wallet','funded_outputs','chain','vaults','address_labels'}) or details['chain'] not in ('main','test','signet','regtest'):raise ValueError('Invalid direct wallet history.')
    if 'address_labels' in details:
        from wallet_labels import validate_labels
        validate_labels(details['address_labels'])
    if 'vaults' in details:
        from vault_policy import public_vault
        if not isinstance(details['vaults'],list) or len(details['vaults'])>128:raise ValueError('Invalid vault list.')
        for v in details['vaults']:
            public_vault(v)
            if v['chain']!=details['chain'] or not descriptors({'wallet_name':'vault','descriptors':[{'desc':v['source']['descriptor']}]}) <= descriptors(details['public_wallet']):raise ValueError('Vault is not derived from this wallet.')
    rows=details['funded_outputs']
    if not isinstance(rows,list) or len(rows)>10000:raise ValueError('Too many funded outputs.')
    seen=set()
    for r in rows:
        if not isinstance(r,dict) or set(r)!={'address','txid','vout','amount_sats','time_received','blockheight','confirmations'}:raise ValueError('Invalid funded output history.')
        if not re.fullmatch('[0-9a-f]{64}',str(r['txid'])) or type(r['vout']) is not int or not 0<=r['vout']<100000 or not isinstance(r['address'],str) or len(r['address'])>256:raise ValueError('Invalid history outpoint.')
        key=(r['txid'],r['vout'])
        if key in seen:raise ValueError('Duplicate history outpoint.')
        seen.add(key)
        if not isinstance(r['amount_sats'],str) or not r['amount_sats'].isdigit() or not 0<int(r['amount_sats'])<=2100000000000000:raise ValueError('Invalid history amount.')
        for field in ('time_received','blockheight','confirmations'):
            if r[field] is not None and (type(r[field]) is not int or not 0<=r[field]<=4102444800):raise ValueError('Invalid history time/height.')

def firewall_verdict(output,peer):
    """Conservative UFW interpretation; unfamiliar rules never mean verified access."""
    peer=ipaddress.IPv6Address(ipv6(peer))
    if output.strip()=='Status: inactive':return {'state':'allowed','message':'UFW is inactive, so it is not blocking the receiving SSH connection. Other firewall software is not checked.'}
    if not output.startswith('Status: active'):return {'state':'unknown','message':'UFW status could not be verified. Use the displayed check command on the receiving computer.'}
    for line in output.splitlines():
        if not ('(v6)' in line or ':' in line):continue
        match=re.match(r'^\s*(.+?)\s{2,}(ALLOW|DENY|REJECT)\s+IN\s+(.+)$',line)
        if not match:
            match=re.match(r'^\s*(22(?:/tcp)?(?:\s+\(v6\))?)\s+(ALLOW|DENY|REJECT)\s+IN\s+(.+)$',line)
        if not match:continue
        target=match[1].replace('(v6)','').strip();src=match[3].split('#')[0].replace('(v6)','').strip()
        if target not in ('Anywhere','22','22/tcp'):return {'state':'unknown','message':'UFW has additional rules whose effect needs manual review. Check the receiving firewall before assuming the modem is blocking it.'}
        try:applies=src=='Anywhere' or peer in ipaddress.IPv6Network(src,strict=False)
        except ValueError:return {'state':'unknown','message':'UFW has a rule that requires manual review.'}
        if applies:
            allowed=match[2]=='ALLOW'
            return {'state':'allowed' if allowed else 'blocked','message':'UFW permits this sender on IPv6 TCP 22.' if allowed else 'UFW has a matching blocking rule. Review its ordering before adding the displayed exception.'}
    return {'state':'unknown','message':'UFW is active; no unambiguous matching inbound IPv6 SSH rule was found. Review the rules and displayed exception on this receiving computer.'}

def check_firewall(transfer):
    key,row=active(transfer.store)
    if not row or row['proposal']['direction']!='receive':raise ValueError('Check the receiving machine firewall from its Synchronisation page.')
    if not Path('/usr/sbin/ufw').exists():
        transfer.firewall={'state':'unknown','message':'UFW is not installed. Other firewall software may still filter SSH; check the receiving computer and modem.'};return transfer.firewall
    try:
        p=subprocess.run(['/usr/bin/pkexec','/usr/sbin/ufw','status','verbose'],capture_output=True,text=True,timeout=120,env={**os.environ,'LC_ALL':'C'})
        if p.returncode:raise ValueError('Firewall check was cancelled or denied. No rules were changed.')
        transfer.firewall=firewall_verdict(p.stdout,row['proposal']['peer']['ipv6'])
    except FileNotFoundError:raise ValueError('Run the displayed sudo ufw status verbose command on this receiving machine.') from None
    return transfer.firewall


def same_facts(a,b):
    # A new tip changes confirmation counts; it must not change any reviewed coin,
    # receiving/change address, amount, receipt time or receipt block height.
    if a.get('vaults',[])!=b.get('vaults',[]) or a.get('address_labels',[])!=b.get('address_labels',[]):return False
    if a.get('public_wallet')!=b.get('public_wallet'):return False
    if a.get('chain')!=b.get('chain') or descriptors(a['public_wallet'])!=descriptors(b['public_wallet']):return False
    def coins(d):return sorted((r['txid'],r['vout'],r['address'],r['amount_sats'],r['time_received'],r['blockheight']) for r in d['funded_outputs'])
    return coins(a)==coins(b)

def route_info(peer):
    """Read current kernel route; never infer locality from an address prefix alone."""
    peer=ipv6(peer)
    try:
        p=subprocess.run(['/usr/bin/ip','-j','-6','route','get',peer],capture_output=True,text=True,timeout=3)
        rows=json.loads(p.stdout)
        if p.returncode or not isinstance(rows,list) or len(rows)!=1:raise ValueError('No unique route.')
        r=rows[0];dev=r.get('dev','');physical=bool(re.fullmatch('[A-Za-z0-9_.:-]{1,32}',dev) and (Path('/sys/class/net')/dev/'device').exists())
        direct=not r.get('gateway') and physical and r.get('type','unicast')=='unicast' and not r.get('encap')
        if direct:message=f'The computer currently selects a direct local IPv6 route on {dev}. The wallet file goes directly over the LAN, not through Wallet Server. SSH still encrypts it. Public preview and coordination messages still use Wallet Server.'
        elif r.get('gateway'):message=f'The computer routes this peer through {r["gateway"]} on {dev}. It may be a local router or an Internet path; this route alone cannot prove where subsequent hops go. The wallet file is still sent directly to the peer over encrypted SSH, not through Wallet Server.'
        else:message=f'The computer selects interface {dev or "unknown"}. A local physical LAN path could not be confirmed; virtual interfaces, VPNs and policy routing can change the path. Wallet files still use direct encrypted SSH.'
        return {'direct_lan':direct,'interface':dev,'gateway':r.get('gateway'),'message':message}
    except (OSError,ValueError,KeyError):return {'direct_lan':False,'interface':None,'gateway':None,'message':'The IPv6 route could not be determined. Check network connectivity; wallet files use direct encrypted SSH, not a Wallet Server relay.'}

def unreachable_message(peer):
    if route_info(peer)['direct_lan']:
        return 'No SSH handshake from the receiving computer on IPv6 TCP 22. The selected route is directly over the LAN: check SSH is running and UFW permits this sender on the receiving computer. If those pass, check Wi-Fi guest/client isolation or VLAN rules, and confirm both peer IPv6 addresses are current. The sender normally needs only outbound TCP 22. An Internet modem port-forward rule is not normally needed for this local path. No password or wallet file was sent.'
    return 'No SSH handshake from the receiving computer on IPv6 TCP 22. On the receiver, check that SSH is running and check its UFW firewall. If the receiver reports UFW permits SSH, a receiving modem/router IPv6 firewall block is suspected: allow inbound IPv6 TCP 22 to the receiver, preferably from this sender only. The sender normally needs only outbound TCP 22. Check VPNs and IPv6 routing too. No password or wallet file was sent.'
