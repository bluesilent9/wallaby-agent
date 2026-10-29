"""Direct, explicitly approved wallet file transfer through system OpenSSH.

Dashboard carries only public pairing metadata. Passwords exist only in memory
and an owner-only askpass socket. No credentials, files or paths reach Dashboard.
"""
import base64,contextlib,hashlib,ipaddress,json,os,pwd,re,secrets,shutil,socket,struct,subprocess,sys,tempfile,threading,time
from pathlib import Path
from approval_store import Store,digest
from build8_policy import ipv6,descriptors
from wallet_ops import rpc

PORT=22
MAX_FILE=256*1024*1024
MAX_HEADER=1024*1024
LIFETIME=900

def local_ipv6(host=None):
    from configuration import Config
    host=host or Config().values.get('hostname')
    if not host:return None
    try:
        for row in socket.getaddrinfo(host,22,socket.AF_INET6,socket.SOCK_DGRAM):
            with socket.socket(socket.AF_INET6,socket.SOCK_DGRAM) as s:
                s.connect(row[4]);return ipv6(s.getsockname()[0])
    except (OSError,ValueError):pass
    return None

def active(store):
    with store.edit() as s:
        key=s.get('active_transfer')
        if key and key in s['pending']:return key,s['pending'][key]
        candidates=[(k,v) for k,v in s['pending'].items() if v['proposal']['kind']=='wallet_transfer' and v['state']=='pending']
        if not candidates:s.pop('active_transfer',None);return None,None
        key,row=min(candidates,key=lambda kv:(kv[1]['proposal']['public_wallet']['wallet_name'].casefold(),kv[0]));s['active_transfer']=key
        return key,row

def frame_write(stream,value):
    raw=json.dumps(value,allow_nan=False,separators=(',',':')).encode()
    if len(raw)>MAX_HEADER:raise ValueError('Transfer header too large.')
    stream.write(struct.pack('!I',len(raw))+raw);stream.flush()

def read_exact(stream,n):
    data=bytearray()
    while len(data)<n:
        part=stream.read(n-len(data))
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
    present=Path('/usr/sbin/sshd').exists();listening=False
    try:listening=bool(subprocess.run(['/usr/bin/ss','-H','-6','-ltn','sport = :22'],capture_output=True,text=True,timeout=3).stdout.strip())
    except OSError:pass
    peer=ipv6(p['peer']['ipv6']);address=local_ipv6()
    return {'installed':present,'listening':listening,'ipv6':address,'username':pwd.getpwuid(os.getuid()).pw_name,'fingerprints':host_fingerprints(),
            'install_command':'sudo apt install openssh-server','start_command':'sudo systemctl start ssh.socket',
            'firewall_check_command':'sudo ufw status verbose','firewall_rule_command':f'sudo ufw allow proto tcp from {peer} to any port 22 comment Wallaby-sync',
            'firewall_remove_command':f'sudo ufw delete allow proto tcp from {peer} to any port 22',
            'network_note':'The receiving SSH server must permit this local account and password authentication. Never enable root login. If UFW is active, its IPv6 support must be enabled (IPV6=yes in /etc/default/ufw). On the receiving modem, allow incoming IPv6 TCP 22 to this computer from the sending IPv6 address. IPv6 normally needs a firewall exception, not IPv4 port forwarding. The Agent cannot reliably inspect your modem or distinguish a modem block from a host firewall or routing failure. System SSH remains controlled by you; closing this transfer closes its direct connection and the Agent receiving socket, not an existing SSH server.'}

def source_wallet(core,p):
    wanted=descriptors(p['public_wallet']);matches=[]
    for name in rpc(core,'listwallets'):
        try:
            raw=rpc(core,'listdescriptors',[False],name)
            if descriptors(raw)==wanted:matches.append(name)
        except ValueError:continue
    if len(matches)!=1:raise ValueError('The local public descriptors must identify exactly one loaded source wallet. Load the wallet and resolve duplicate replicas first.')
    info=rpc(core,'getwalletinfo',[],matches[0])
    if info.get('private_keys_enabled')!=p['source_has_private_keys'] or info.get('scanning'):raise ValueError('Source wallet key capability changed or its scan is incomplete.')
    if info.get('private_keys_enabled') and ('unlocked_until' not in info or info['unlocked_until']!=0):raise ValueError('Lock this encrypted wallet in Bitcoin Core before sending. Unencrypted private-key wallets cannot be transferred; encrypt and back up the wallet in Core first.')
    return matches[0]

def wallet_details(core,p):
    """Funded address facts originate at Core, transferred peer-to-peer, never asserted by Dashboard."""
    name=source_wallet(core,p)
    current={}
    history=rpc(core,'listsinceblock',[],name).get('transactions',[])
    if len(history)>100000:raise ValueError('Wallet history exceeds the safe review limit.')
    for tx in history:
        if tx.get('category') not in ('receive','generate','immature') or type(tx.get('vout')) is not int:continue
        key=(tx['txid'],tx['vout'])
        if key in current:continue
        coin=rpc(core,'gettxout',[key[0],key[1],True])
        if coin and __import__('wallet_ops').sats(coin['value'])>0:current[key]={'txid':key[0],'vout':key[1],'amount':coin['value'],'address':coin['scriptPubKey'].get('address','Unknown script'),'confirmations':coin.get('confirmations',0)}
    utxos=list(current.values());rows=[];heights={}
    if len(utxos)>10000:raise ValueError('Wallet has too many funded outputs for one review.')
    for u in utxos:
        tx=rpc(core,'gettransaction',[u['txid'],True],name);height=None
        if tx.get('blockhash'):
            h=tx['blockhash']
            if h not in heights:heights[h]=rpc(core,'getblockheader',[h])['height']
            height=heights[h]
        rows.append({'address':u.get('address','Unknown script'),'txid':u['txid'],'vout':u['vout'],'amount_sats':str(__import__('wallet_ops').sats(u['amount'])),'time_received':tx.get('timereceived',tx.get('time')),'blockheight':height,'confirmations':u.get('confirmations',0)})
    return {'public_wallet':rpc(core,'listdescriptors',[False],name),'funded_outputs':rows,'chain':rpc(core,'getblockchaininfo')['chain']}

def work_dir(core):
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
        if self.success_until>time.time():return {'id':None,'success_until':self.success_until}
        key,row=active(self.store)
        if self.listener and time.monotonic()>self.deadline:self.close();self.error='Receiving authorisation expired. Review and authorise again.'
        preview=self.store.read().get('transfer_previews',{}).get(key) if key else None
        proof={}
        if preview:
            from wallet_preview import fingerprint
            proof={'fingerprint':fingerprint(preview['public_key']),'preview_hash':digest(preview['preview'])}
            self.details={k:preview['preview'][k] for k in ('public_wallet','chain','funded_outputs')}
        return {'route':route_info(row['proposal']['peer']['ipv6']) if row else None,'initial_preview':preview,'preview_proof':proof,'preview_error':self.store.read().get('preview_error',''),'id':key,'proposal':row['proposal'] if row else None,'state':row['state'] if row else None,'ready':bool(self.listener),'sending':getattr(self,'sending',False),'firewall':self.firewall,'details':self.details,'error':self.error,'success_until':self.success_until,'setup':readiness(row['proposal']) if row else None}
    def review(self,key):
        current,row=active(self.store)
        if key!=current or not row or row['state']!='pending':raise ValueError('This is not the active synchronisation request.')
        p=row['proposal']
        if p['direction']=='send':
            if p.get('preview_challenge'):
                from wallet_preview import prepare
                if key not in self.store.read().get('transfer_previews',{}):prepare(self.core,self.store,key,p)
            else:self.details=wallet_details(self.core,p)
        else:self.details=None
        return self.state()
    def authorise(self,key,sender_fingerprint):
        with self.lock:
            current,row=active(self.store)
            if key!=current or not row or row['proposal']['direction']!='receive':raise ValueError('Review the active receiving request.')
            from wallet_preview import verify
            payload=self.store.read().get('transfer_previews',{}).get(key)
            if not row['proposal'].get('preview_challenge') or not payload:raise ValueError('The initial node-verified wallet preview is missing. Dashboard Build 8 needs the documented preview protocol update; receiving is disabled until then.')
            proof=verify(self.store,payload)
            if sender_fingerprint!=proof['fingerprint']:raise ValueError('The Agent identity fingerprint must match the sending Agent’s own screen. Dashboard is not a trusted source for it.')
            if row['state']!='pending':raise ValueError('This receiving request was already attempted. Reconcile it before retrying.')
            if not readiness(row['proposal'])['listening']:raise ValueError('Start the receiving machine’s IPv6 SSH listener using the displayed instructions, then Authorise again.')
            if self.thread and self.thread.is_alive():raise ValueError('Receiving is already active. Finish or cancel it first.')
            self.close();self.manifest_approved=False;self.error='';path=socket_path(self.store)
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
    def cancel(self,key):
        # Never claim a failed/uncertain restore succeeded or automatically replay it.
        current,row=active(self.store)
        if key!=current:raise ValueError('Active request changed.')
        if getattr(self,'sending',False) or (row['state']=='attempted' and self.thread and self.thread.is_alive()):raise ValueError('Wallet transfer/restoration is running. Wait for its result before cancelling.')
        self.close()
        with self.store.edit() as s:s.pop('active_transfer',None)
        self.store.deny(key);self.details=None
    def receive(self,key,p):
        conn=None;path=None;listener=self.listener
        try:
            listener=self.listener
            while self.listener is listener and time.monotonic()<self.deadline:
                try:conn,_=listener.accept();break
                except socket.timeout:continue
            if conn is None:return
            uid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
            if uid!=os.getuid():raise ValueError('Incoming SSH account differs from the authorised local user.')
            self.connection=conn
            conn.settimeout(LIFETIME);stream=conn.makefile('rwb',buffering=0);header=frame_read(stream)
            if header.get('operation')!='manifest' or header.get('transfer_id')!=p['transfer_id'] or ipv6(header.get('peer_ipv6'))!=ipv6(p['peer']['ipv6']):raise ValueError('Transfer or authenticated SSH source address differs from the approved request.')
            details=header.get('details');wanted=descriptors(p['public_wallet'])
            if not isinstance(details,dict) or descriptors(details.get('public_wallet'))!=wanted or details.get('chain')!=rpc(self.core,'getblockchaininfo')['chain']:raise ValueError('Direct peer public wallet does not match the approved descriptors/network.')
            # A second local click approves the actual live peer history, not server-provided claims.
            validate_details(details)
            preview=self.store.read().get('transfer_previews',{}).get(key)
            if not preview or not same_facts(details,{k:preview['preview'][k] for k in ('public_wallet','chain','funded_outputs')}):raise ValueError('Live SSH wallet details differ from the independently verified initial preview. Cancel and start a fresh request.')
            self.details=details
            frame_write(stream,{'status':'review_required'})
            frame_write(stream,{'status':'ready'})
            header=frame_read(stream)
            if set(header)!={'size','sha256'} or type(header['size']) is not int or not 0<header['size']<=MAX_FILE or not re.fullmatch('[0-9a-f]{64}',header['sha256']):raise ValueError('Invalid encrypted wallet file header.')
            # Never overwrite a wallet, even if the server chose an existing name.
            for name in rpc(self.core,'listwallets'):
                try:
                    if descriptors(rpc(self.core,'listdescriptors',[False],name)) & wanted:raise FileExistsError('This wallet is already present locally.')
                except ValueError:continue
            root=work_dir(self.core);fd,filename=tempfile.mkstemp(prefix='receive-',dir=root);path=Path(filename);hasher=hashlib.sha256();remaining=header['size']
            with os.fdopen(fd,'wb') as out:
                while remaining:
                    chunk=read_exact(stream,min(65536,remaining));out.write(chunk);hasher.update(chunk);remaining-=len(chunk)
                out.flush();os.fsync(out.fileno())
            if hasher.hexdigest()!=header['sha256']:raise ValueError('Wallet file integrity check failed.')
            with self.store.edit() as s:s['pending'][key]['state']='attempted'
            name='Wallaby Sync '+p['transfer_id'][:24]
            if any(w['name']==name for w in rpc(self.core,'listwalletdir')['wallets']):raise ValueError('A previous restoration exists. Inspect it in Core; it will not be overwritten.')
            rpc(self.core,'restorewallet',{'wallet_name':name,'backup_file':str(path),'load_on_startup':True},timeout=600)
            info=rpc(self.core,'getwalletinfo',[],name);actual=descriptors(rpc(self.core,'listdescriptors',[False],name))
            if actual!=wanted or info.get('private_keys_enabled')!=p['source_has_private_keys'] or (info.get('private_keys_enabled') and ('unlocked_until' not in info or info['unlocked_until']!=0)) or info.get('scanning'):
                rpc(self.core,'unloadwallet',{'wallet_name':name,'load_on_startup':False});raise ValueError('Restored wallet failed descriptor, encryption or scan verification; unloaded. Inspect it in Core before retrying.')
            for output in details['funded_outputs']:
                coin=rpc(self.core,'gettxout',[output['txid'],output['vout'],True])
                if not coin or str(__import__('wallet_ops').sats(coin['value']))!=output['amount_sats'] or coin['scriptPubKey'].get('address')!=output['address']:
                    raise ValueError('A funded output is missing or changed on the receiving node. Check blockchain synchronisation and wallet history before retrying; success was not recorded.')
                rpc(self.core,'gettransaction',[output['txid'],True],name)
            self.complete(key);frame_write(stream,{'status':'loaded','transfer_id':p['transfer_id'],'wallet_identity':digest(sorted(actual))})
            # Sender explicitly confirms learning the receiver loaded successfully.
            frame_read(stream)
        except Exception as e:
            self.error=str(e) if isinstance(e,(ValueError,FileExistsError)) else 'Direct transfer failed or its outcome is uncertain. Inspect Core before retrying.'
            if conn:
                try:frame_write(conn.makefile('rwb',buffering=0),{'status':'error','message':self.error})
                except OSError:pass
        finally:
            if path:path.unlink(missing_ok=True)
            if conn:conn.close()
            self.connection=None
            if self.listener is listener:self.close()
    def send(self,key,username,password,fingerprint):
        with self.lock:
            current,row=active(self.store)
            if key!=current or not row or row['state']!='pending' or row['proposal']['direction']!='send':raise ValueError('Review the active sending request.')
            if not isinstance(username,str) or not re.fullmatch('[a-z_][a-z0-9_-]{0,63}',username):raise ValueError('Enter the receiving machine’s local username.')
            if not isinstance(password,str) or len(password)>1024 or '\n' in password or '\r' in password:raise ValueError('Invalid receiving login password.')
            if not isinstance(fingerprint,str) or not re.fullmatch('SHA256:[A-Za-z0-9+/]{43}',fingerprint):raise ValueError('Compare and enter the fingerprint shown on the receiving Agent. Do not obtain it from Dashboard.')
            payload=self.store.read().get('transfer_previews',{}).get(key)
            if not row['proposal'].get('preview_challenge') or not payload:raise ValueError('Dashboard needs the initial signed-preview protocol update before this wallet can be sent. No credentials or wallet file were sent.')
            from wallet_preview import verify
            verify(self.store,payload)
            p=row['proposal'];peer=ipv6(p['peer']['ipv6']);own=local_ipv6(peer)
            if not own:raise ValueError('No routable local IPv6 route to the receiving peer.')
            details=wallet_details(self.core,p)
            if not same_facts(details,{k:payload['preview'][k] for k in ('public_wallet','chain','funded_outputs')}):raise ValueError('Wallet history changed. Review the current sending details again before sending.')
            validate_details(details)
            name=source_wallet(self.core,p);self.details=details
            with tempfile.TemporaryDirectory(prefix='send-',dir=work_dir(self.core)) as d:
                root=Path(d);backup=root/'wallet.dat';known=root/'known_hosts';ask=self.store.root/('askpass-'+secrets.token_hex(6)+'.sock');process=None;auth=None;errors=bytearray()
                try:
                    scan=subprocess.run(['/usr/bin/ssh-keyscan','-6','-T','5','-p',str(PORT),peer],capture_output=True,text=True,timeout=20)
                    matched=[]
                    for line in scan.stdout.splitlines():
                        fields=line.split()
                        if len(fields)!=3:continue
                        value='SHA256:'+base64.b64encode(hashlib.sha256(base64.b64decode(fields[2],validate=True)).digest()).decode().rstrip('=')
                        if value==fingerprint:matched.append(line)
                    if not matched:
                        if scan.stdout.strip():raise ValueError('The receiving SSH host key does not match the fingerprint you entered. Compare it directly with the receiving Agent. No password or wallet file was sent.')
                        raise ValueError(unreachable_message(peer))
                    known.write_text('\n'.join(matched)+'\n');known.chmod(0o600)
                    auth=socket.socket(socket.AF_UNIX);auth.bind(str(ask));ask.chmod(0o600);auth.listen(1);auth.settimeout(30)
                    def answer():
                        try:
                            c,_=auth.accept()
                            with c:
                                if struct.unpack('3i',c.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]==os.getuid():c.sendall(password.encode()+b'\n')
                        except OSError:pass
                    threading.Thread(target=answer,daemon=True).start()
                    env={**os.environ,'SSH_ASKPASS':'/usr/bin/wallaby-agent','SSH_ASKPASS_REQUIRE':'force','DISPLAY':os.environ.get('DISPLAY',':0'),'WALLABY_ASKPASS_SOCKET':str(ask)}
                    cmd=['/usr/bin/ssh','-6','-b',own,'-F','/dev/null','-T','-p',str(PORT),'-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),'-o','GlobalKnownHostsFile=/dev/null','-o','PreferredAuthentications=password','-o','PubkeyAuthentication=no','-o','NumberOfPasswordPrompts=1','-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','ForwardAgent=no','-o','ClearAllForwardings=yes',username+'@'+peer,'/usr/bin/wallaby-agent peer-receive']
                    process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,start_new_session=True)
                    def drain():
                        while True:
                            chunk=process.stderr.read(1024)
                            if not chunk:break
                            if len(errors)<8192:errors.extend(chunk[:8192-len(errors)])
                    threading.Thread(target=drain,daemon=True).start()
                    # Deadline covers peer review, file transfer and restoration; never replay automatically.
                    timer=threading.Timer(LIFETIME,process.kill);timer.daemon=True;timer.start()
                    try:
                        frame_write(process.stdin,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':own,'details':details})
                        reply=frame_read(process.stdout)
                        if reply.get('status')!='review_required':raise ValueError('Receiver did not accept this paired request. Authorise on the receiving Agent first.')
                        reply=frame_read(process.stdout)
                        if reply.get('status')!='ready':raise ValueError('Receiver did not approve the direct wallet history.')
                        # Revalidate the source immediately before making a consistent Core backup.
                        source_wallet(self.core,p);rpc(self.core,'backupwallet',[str(backup)],name)
                        size=backup.stat().st_size
                        if not 0<size<=MAX_FILE:raise ValueError('Wallet backup exceeds the 256 MiB transfer limit.')
                        h=hashlib.sha256()
                        with backup.open('rb') as f:
                            for chunk in iter(lambda:f.read(65536),b''):h.update(chunk)
                        with self.store.edit() as s:s['pending'][key]['state']='attempted'
                        frame_write(process.stdin,{'size':size,'sha256':h.hexdigest()})
                        with backup.open('rb') as f:shutil.copyfileobj(f,process.stdin,65536)
                        process.stdin.flush();reply=frame_read(process.stdout)
                        if reply.get('status')!='loaded' or reply.get('transfer_id')!=p['transfer_id'] or reply.get('wallet_identity')!=digest(sorted(descriptors(p['public_wallet']))):raise ValueError('Receiver did not confirm a matching, loaded wallet. Check both Core instances before retrying.')
                        frame_write(process.stdin,{'status':'confirmed'});self.complete(key);return {'ok':True}
                    except (ValueError,BrokenPipeError,OSError) as error:
                        text=errors.decode(errors='replace').lower()
                        if 'permission denied' in text:raise ValueError('SSH login was rejected by the receiving computer. Check its local username and computer login password; ensure that account is permitted to log in and that the receiver allows password authentication. This is not the Bitcoin wallet passphrase. The wallet file was not sent before login.') from None
                        if 'invalid choice' in text or 'no such file' in text:raise ValueError('The receiving machine needs this Agent build and its locally authorised Synchronisation page. Update and open the receiving Agent before retrying.') from None
                        if 'timed out' in text or 'no route' in text or 'connection refused' in text:raise ValueError('Direct SSH to the receiver failed. Check SSH and UFW on the receiver, then its modem’s inbound IPv6 TCP 22 exception. If the sender restricts outgoing traffic, allow outbound TCP 22. Check VPNs and that both displayed IPv6 addresses are current.') from None
                        raise ValueError(str(error)+' Check both Agents; confirm Authorise was clicked on the receiver and review any receiver error. If a transfer was attempted, inspect Core before retrying.') from None
                    finally:timer.cancel()
                finally:
                    if process and process.poll() is None:process.kill()
                    if process:process.wait(timeout=5)
                    if auth:auth.close()
                    ask.unlink(missing_ok=True)
                    password=None

def peer_receive():
    # Called as the logged-in SSH user. Relay only; no RPC/file paths accepted here.
    source=os.environ.get('SSH_CONNECTION','').split()
    if len(source)!=4:raise ValueError('This command is only available through an SSH session.')
    address=ipv6(source[0]);store=Store();key,row=active(store)
    if not row or row['proposal']['direction']!='receive' or ipv6(row['proposal']['peer']['ipv6'])!=address:raise ValueError('No locally authorised request for this SSH peer.')
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(LIFETIME);s.connect(str(socket_path(store)))
        # Verify the peer-claimed IP against sshd, then reconstruct the framed header.
        header=frame_read(sys.stdin.buffer)
        if header.get('peer_ipv6')!=address:raise ValueError('SSH source differs from transfer header.')
        remote=s.makefile('rwb',buffering=0);frame_write(remote,header)
        def upload():
            try:
                while True:
                    data=os.read(sys.stdin.fileno(),65536)
                    if not data:break
                    s.sendall(data)
                s.shutdown(socket.SHUT_WR)
            except OSError:pass
        threading.Thread(target=upload,daemon=True).start()
        while True:
            data=s.recv(65536)
            if not data:break
            sys.stdout.buffer.write(data);sys.stdout.buffer.flush()

def askpass():
    path=Path(os.environ['WALLABY_ASKPASS_SOCKET'])
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(30);s.connect(str(path));data=s.recv(4096)
        sys.stdout.buffer.write(data);sys.stdout.buffer.flush()

def validate_details(details):
    if set(details)!={'public_wallet','funded_outputs','chain'} or details['chain'] not in ('main','test','signet','regtest'):raise ValueError('Invalid direct wallet history.')
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
        if direct:message=f'The computer currently selects a direct local IPv6 route on {dev}. The wallet file goes directly over the LAN, not through Dashboard. SSH still encrypts it. Public preview and coordination messages still use Dashboard.'
        elif r.get('gateway'):message=f'The computer routes this peer through {r["gateway"]} on {dev}. It may be a local router or an Internet path; this route alone cannot prove where subsequent hops go. The wallet file is still sent directly to the peer over encrypted SSH, not through Dashboard.'
        else:message=f'The computer selects interface {dev or "unknown"}. A local physical LAN path could not be confirmed; virtual interfaces, VPNs and policy routing can change the path. Wallet files still use direct encrypted SSH.'
        return {'direct_lan':direct,'interface':dev,'gateway':r.get('gateway'),'message':message}
    except (OSError,ValueError,KeyError):return {'direct_lan':False,'interface':None,'gateway':None,'message':'The IPv6 route could not be determined. Check network connectivity; wallet files use direct encrypted SSH, not a Dashboard relay.'}

def unreachable_message(peer):
    if route_info(peer)['direct_lan']:
        return 'No SSH handshake from the receiving computer on IPv6 TCP 22. The selected route is directly over the LAN: check SSH is running and UFW permits this sender on the receiving computer. If those pass, check Wi-Fi guest/client isolation or VLAN rules, and confirm both peer IPv6 addresses are current. The sender normally needs only outbound TCP 22. An Internet modem port-forward rule is not normally needed for this local path. No password or wallet file was sent.'
    return 'No SSH handshake from the receiving computer on IPv6 TCP 22. On the receiver, check that SSH is running and check its UFW firewall. If the receiver reports UFW permits SSH, a receiving modem/router IPv6 firewall block is suspected: allow inbound IPv6 TCP 22 to the receiver, preferably from this sender only. The sender normally needs only outbound TCP 22. Check VPNs and IPv6 routing too. No password or wallet file was sent.'
