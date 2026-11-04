"""User-chosen encrypted optical recovery into the protected temporary Core only."""
import copy,fcntl,hashlib,json,os,re,secrets,shutil,stat,struct,subprocess,threading,zipfile
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc
from wallet_setup import MemoryCore,secret_dialog
from setup_policy import policy
from setup_messages import verify
from build8_policy import descriptors
from disc_backup import decrypt_file
from disc_archive import recover,direct_read,decode_header,align,HEADER,MAX_PACKAGE,MAX_MEDIA
from vendor.embit.descriptor import Descriptor
from vendor.embit.descriptor.checksum import checksum
from vendor.embit.networks import NETWORKS
MAX_ACCOUNTS=64

class Archives:
    def __init__(self,core,store,binary,enforce):
        self.core=core;self.store=store;self.binary=binary;self.enforce=enforce;self.loaded={};self.staged={};self.error='';self.message='';self.reading=False;self.lock=threading.RLock();self.local=threading.local();self.catalogs={}
    def route(self,core,ident,method,params,wallet,timeout):
        if core.config!=self.core.config or getattr(self.local,'bypass',False):return None
        with self.lock:
            records=list(self.loaded.values())
            for record in records:
                if wallet in record['routes']:
                    if method not in ('walletprocesspsbt','walletpassphrase','walletlock'):
                        from agent_rpc import request
                        request(method,params,wallet)
                    result=record['node'].core.call(ident,method,params,record['routes'][wallet],timeout)
                    if method=='getwalletinfo' and isinstance(result.get('result'),dict):result['result'].update(wallaby_storage='disc',wallaby_archive_id=record.get('archive_id'),wallaby_policy_hash=record['recovery']['policy_hash'])
                    return result
            if method in ('listwallets','listwalletdir') and wallet is None:
                self.local.bypass=True
                try:r=core.call(ident,method,params,None,timeout)
                finally:self.local.bypass=False
                if 'result' not in r:return r
                names=[name for rec in records for name in rec['routes']]
                if method=='listwallets':r['result']+=names
                else:r['result']['wallets'] += [{'name':n} for n in names]
                return r
        return None
    def state(self):
        with self.lock:return {'reading':self.reading,'message':self.message,'error':self.error,'staged':[r['review'] for r in self.staged.values()],'loaded':[{'id':k,**{field:r['review'].get(field) for field in ('name','cosigner','cosigner_id','signer_number','threshold','total','chain','height','effective_policy_hash')},'policy_hash':r['recovery']['policy_hash'],'wallets':r['keys'],'monitor':r['monitor'],'storage':'Protected RAM only','archive_id':r.get('archive_id')} for k,r in self.loaded.items()]}
    def inspect(self,device,password):
        self.enforce()
        if not isinstance(device,str) or not re.fullmatch('/dev/sr[0-9]{1,2}',device):raise ValueError('Choose a local optical drive.')
        st=os.stat(device,follow_symlinks=False)
        if not stat.S_ISBLK(st.st_mode) or os.major(st.st_rdev)!=11:raise ValueError('Choose a Linux optical device.')
        folder=self.store.root/'disc-read'/secrets.token_hex(16);folder.mkdir(mode=0o700,parents=True);encrypted=folder/'recovery.wallaby'
        try:
            fd=os.open(device,os.O_RDONLY|os.O_DIRECT)
            try:
                capacity=struct.unpack('<Q',fcntl.ioctl(fd,0x80081272,bytes(8)))[0]
                if not 0<capacity<=MAX_MEDIA:raise ValueError('Cannot determine safe readable disc capacity.')
                try:
                    hint=None
                    try:
                        pvd=direct_read(fd,32768,4096)
                        if pvd[1:6]==b'CD001':hint=align(int.from_bytes(pvd[80:84],'little')*2048)
                    except OSError:pass
                    recover(fd,capacity,encrypted,start_hint=hint,progress=lambda message:setattr(self,'message',message))
                except ValueError:
                    # Build 9's single-copy ISO has no redundant-track headers.
                    self.message='Checking the earlier single-copy recovery format.'
                    def limits():
                        import resource
                        resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_PACKAGE,MAX_PACKAGE))
                    result=subprocess.run(['/usr/bin/xorriso','-abort_on','FAILURE','-osirrox','on','-indev',device,'-extract','/recovery.wallaby',str(encrypted),'-end'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=300,preexec_fn=limits)
                    if result.returncode or not encrypted.is_file() or not 64<=encrypted.stat().st_size<=MAX_PACKAGE:raise ValueError('No readable authenticated recovery package was found. Try another disc or optical drive.')
            finally:os.close(fd)
            return self.inspect_package(encrypted,password,folder)
        except Exception:shutil.rmtree(folder);raise
    def inspect_package(self,encrypted,password,folder=None):
        self.enforce();folder=Path(folder or encrypted.parent);plain=folder/'recovery.zip'
        with open(encrypted,'rb') as stream:archive_id=hashlib.file_digest(stream,'sha256').hexdigest()
        from disc_backup import require_space
        require_space(folder,2*Path(encrypted).stat().st_size+256*1024*1024)
        decrypt_file(encrypted,plain,password);password=None;prepared=[]
        try:
            with zipfile.ZipFile(plain) as z:
                infos=z.infolist();names=[i.filename for i in infos]
                if len(set(names))!=len(names) or not 2<=len(names)<=16 or 'policy.json' not in names or sum(i.file_size for i in infos)>MAX_PACKAGE or any(i.flag_bits&1 for i in infos):raise ValueError('Invalid or oversized recovery archive.')
                if z.getinfo('policy.json').file_size>4*1024*1024:raise ValueError('Recovery policy exceeds safe limits.')
                recovery=json.loads(z.read('policy.json'))
                if recovery.get('version')==2:
                    from archive_format import validate
                    validate(recovery);entries=recovery['entries']
                    if set(names)!={'policy.json'}|{'wallets/'+e['id']+'.dat' for e in entries}:raise ValueError('Archive files differ from the authenticated wallet set.')
                else:
                    role=recovery.get('physical_cosigner_file');entries=[{'id':role,'kind':'setup_role','recovery':recovery}]
                    if set(names)!={'policy.json','wallets/'+str(role)+'.dat'}:raise ValueError('Legacy disc must contain exactly its assigned physical role.')
                if len(self.staged)+len(self.loaded)+len(entries)>MAX_ACCOUNTS:raise ValueError('The protected session supports up to 64 staged/loaded signing accounts across discs, subject to available RAM. Remove unused accounts before reading this wallet set.')
                for entry in entries:
                    target=folder/str(entry['id']);target.mkdir(mode=0o700)
                    prepared.append(self.stage_entry(entry['recovery'],z,'wallets/'+entry['id']+'.dat',target,archive_id))
            from archive_format import identity
            from archive_inventory import member
            from setup_messages import sign
            self.store.queue('archive_inventory',sign(self.store,{'version':1,'event':'archive_observed','archive_id':archive_id,'payload_sha256':archive_id,'payload_verified':True,'readback_verified':False,'replacements':[],'members':[member(r['recovery']) for _,r in prepared]}))
            with self.lock:
                self.catalogs[archive_id]={identity(r['recovery']):copy.deepcopy(r['recovery']) for ident,r in prepared}
                for ident,row in prepared:self.staged[ident]=row
            return prepared[0][1]['review'] if recovery.get('version')==1 else {'archive_id':archive_id,'entries':[r['review'] for ident,r in prepared]}
        except Exception:
            for ident,row in prepared:shutil.rmtree(row['folder'],ignore_errors=True)
            raise
        finally:plain.unlink(missing_ok=True)
    def stage_entry(self,recovery,z,wallet_name,folder,archive_id):
        from archive_format import entry_kind,validate_node
        generic=entry_kind(recovery)=='node_wallet'
        if generic:
            validate_node(recovery);p={'name':recovery['name'],'chain':recovery['chain'],'threshold':1,'cosigners':[{}],'height':None};expected=recovery['policy_hash'];descs=[r['desc'] for r in recovery['public_wallet']['descriptors']];role={'id':'node-wallet','name':recovery['name']}
        else:
            p=recovery['proposal'];roles={r['id']:r for r in p['cosigners']};contributions=[]
            for envelope in recovery['contributions']:
                ident=envelope.get('message',{}).get('cosigner_id')
                if ident not in roles:raise ValueError('Unknown recovered cosigner.')
                contributions.append(verify(self.store,envelope,roles[ident]['agent_key']))
            descs=policy(p,contributions,allow_expired=True);expected=digest({'proposal':p,'receive_descriptor':descs[0],'change_descriptor':descs[1],'contributions':recovery['contributions']})
            if descs!=[recovery['receive_descriptor'],recovery['change_descriptor']] or expected!=recovery['policy_hash']:raise ValueError('Recovered complete policy differs from its signed contributions or policy code.')
            matches=[r for r in p['cosigners'] if r['storage']=='disc' and hashlib.sha256(r['id'].encode()).hexdigest()==recovery.get('physical_cosigner_file')]
            if len(matches)!=1 or recovery.get('local_cosigners')!=[matches[0]['id']]:raise ValueError('Invalid physical signing role.')
            role=matches[0]
        if rpc(self.core,'getblockchaininfo')['chain']!=p['chain']:raise ValueError('Disc network does not match the connected node.')
        from policy_refresh import validate_extensions
        effective=validate_extensions(recovery)
        effective_height=__import__('wallet_setup_signing').restricted(effective[0])['height'] if effective and __import__('wallet_setup_signing').restricted(effective[0]) else p['height']
        wallet=folder/'encrypted-wallet.dat'
        with z.open(wallet_name) as inp,open(wallet,'wb') as out:
            os.chmod(wallet,0o600);shutil.copyfileobj(inp,out,1024*1024)
        ident=secrets.token_hex(16);samples=[]
        for i,desc in enumerate((effective or descs)[:2]):
            try:
                d=Descriptor.from_string(desc);sample=d.derive(0) if d.is_wildcard else d;samples.append({'branch':'Receiving' if i==0 else 'Change','address':sample.script_pubkey().address(NETWORKS[p['chain']])})
            except Exception:pass
        if 'display_name' in recovery:__import__('wallet_rename').name(recovery['display_name'])
        review={'id':ident,'name':recovery.get('display_name',p['name']),'threshold':p['threshold'],'total':len(p['cosigners']),'height':effective_height,'effective_policy_hash':digest(recovery.get('policy_extensions',[])),'chain':p['chain'],'cosigner':role['name'],'cosigner_id':role['id'],'policy_hash':expected,'receive_descriptor':descs[0],'change_descriptor':descs[1] if len(descs)>1 else descs[0],'samples':samples,'archive_id':archive_id,'additional_policies':recovery.get('policy_extensions',[])}
        review['signer_number']=1 if generic else next(i+1 for i,item in enumerate(p['cosigners']) if item['id']==role['id'])
        return ident,{'review':review,'recovery':recovery,'folder':folder,'wallet':wallet,'role':role,'archive_id':archive_id,'generic':generic}
    def load(self,ident,confirmed):
        self.enforce()
        if confirmed is not True:raise ValueError('Compare the policy code and addresses against your trusted wallet record before loading.')
        with self.lock:
            r=self.staged.get(ident)
            if not r:raise ValueError('Read and review the disc first.')
            if any(v['recovery']['policy_hash']==r['recovery']['policy_hash'] and v['role']['id']==r['role']['id'] for v in self.loaded.values()):raise ValueError('That exact physical signing key is already loaded.')
            from disc_backup import require_space
            require_space(r['folder'],2*r['wallet'].stat().st_size+128*1024*1024)
            node=MemoryCore(r['folder']/'node',r['review']['chain'],self.binary)
            try:
                c=node.core;rpc(c,'restorewallet',{'wallet_name':'archive-key','backup_file':str(r['wallet']),'load_on_startup':False})
                info=rpc(c,'getwalletinfo',[],'archive-key')
                if not info.get('private_keys_enabled') or 'unlocked_until' not in info or info['unlocked_until']!=0:raise ValueError('The archived signing wallet must be encrypted, locked and private-key enabled.')
                if r.get('generic'):
                    wanted=r['recovery']['public_wallet']
                else:
                    contribution=next(e['message'] for e in r['recovery']['contributions'] if e['message']['cosigner_id']==r['role']['id'])
                    wanted={'wallet_name':'archive-key','descriptors':[{'desc':'wpkh('+contribution[k]+')#'+checksum('wpkh('+contribution[k]+')')} for k in ('receive_key','change_key')]}
                    if r['recovery'].get('wallet_layout')=='combined-policy-key-v1':
                        from combined_wallet import public_policy,verify_private_role
                        wanted=public_policy(r['recovery'])
                        password=secret_dialog('Unlock archived signing role: '+r['role']['name']+' · '+r['review']['name'],getattr(self,'environment',{}))
                        try:
                            rpc(c,'walletpassphrase',[password,120],'archive-key')
                            verify_private_role(node,'archive-key',contribution)
                        finally:
                            password=None;rpc(c,'walletlock',[],'archive-key')
                if not descriptors(wanted)<=descriptors(rpc(c,'listdescriptors',[False],'archive-key')):raise ValueError('Archived private wallet public account does not match the approved recovery policy.')
                rpc(c,'createwallet',{'wallet_name':'archive-policy','disable_private_keys':True,'blank':True,'descriptors':True,'load_on_startup':False})
                if r.get('generic'):
                    requests=[{k:v for k,v in row.items() if k in ('desc','timestamp','active','internal','range','next_index')} for row in r['recovery'].get('public_policies',r['recovery']['public_wallet'])['descriptors']]
                    for original,row in zip(r['recovery'].get('public_policies',r['recovery']['public_wallet'])['descriptors'],requests):
                        row['timestamp']='now'
                        if 'next' in original:row['next_index']=original['next']
                else:requests=[{'desc':r['recovery'][k],'timestamp':'now','active':True,'internal':bool(i),'range':[0,999]} for i,k in enumerate(('receive_descriptor','change_descriptor'))]
                for ext in r['recovery'].get('policy_extensions',[]):
                    requests.extend({'desc':desc,'timestamp':'now','active':False,'internal':bool(i),'range':[0,999]} for i,desc in enumerate((ext['receive_descriptor'],ext['change_descriptor'])))
                result=rpc(c,'importdescriptors',[requests],'archive-policy')
                if any(not x.get('success') for x in result):raise ValueError('Could not load the complete public archive policy in RAM.')
                if r.get('generic') and r['recovery'].get('policy_labels'):
                    from wallet_labels import apply_labels
                    apply_labels(c,'archive-policy',r['recovery']['policy_labels'],write=True)
                # Explicit local restore approval, never a remotely asserted ready bit.
                first=r['review']['receive_descriptor'];address=rpc(c,'deriveaddresses',[first,[0,0]] if '*' in first else [first])[0];None if r.get('generic') else rpc(c,'setlabel',[address,'Wallaby setup ready:'+r['recovery']['policy_hash']],'archive-policy')
                label='Disc '+(r['recovery']['display_name']+' ' if r['recovery'].get('display_name') else '')+r['recovery']['policy_hash'][:12]+' '+r['role']['id'];monitor=label+' policy';routes={label:'archive-key',monitor:'archive-policy'}
                r.update(node=node,routes=routes,keys=[label],monitor=monitor);self.loaded[ident]=r;self.staged.pop(ident)
            except Exception:node.close();raise
            return {'message':'Archive key loaded in protected RAM. Request its signature from Dashboard, then review it on Authorise. It will be lost when unloaded or this workspace closes.'}
    def unload(self,ident):
        self.enforce()
        with self.lock:
            r=self.loaded.get(ident)
            if r:r['node'].close();self.loaded.pop(ident)
            else:r=self.staged.pop(ident,None)
            if not r:raise ValueError('Archive is no longer loaded.')
            shutil.rmtree(r['folder']);return {'message':'Archive closed and its temporary RAM files removed.'}
