"""Two local approvals: participation/key generation, then exact complete public policy."""
import hashlib,os,secrets,shutil,socket,subprocess,time
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc
from wallet_preview import fingerprint
from setup_messages import sign,verify
from setup_policy import proposal,policy
from vendor.embit.networks import NETWORKS
from vendor.embit.descriptor import Descriptor
from disc_backup import Burner
from diagnostics import LocalActionFailure


def secret_dialog(prompt,environment,confirm=False):
    import json,importlib.util
    try:available=importlib.util.find_spec('PyQt6.QtWidgets') is not None
    except (ImportError,ValueError):available=False
    if not available:raise LocalActionFailure('native_dialog_missing','Install python3-pyqt6 for the protected native passphrase dialogue. No secret was requested through the browser.')
    env={**os.environ,**environment};env['QT_LOGGING_RULES']='*.debug=false;*.info=false'
    command=['/usr/bin/python3','-I','-B',str(Path(__file__).resolve().with_name('secret_prompt.py'))]
    try:result=subprocess.run(command,input=json.dumps({'prompt':prompt,'confirm':confirm}).encode(),capture_output=True,timeout=300,env=env)
    except subprocess.TimeoutExpired:raise ValueError('Local secret entry cancelled. No operation was authorised.') from None
    if result.returncode==1:raise ValueError('Local secret entry cancelled. No operation was authorised.')
    if result.returncode:raise LocalActionFailure('native_dialog_failed','The protected native passphrase dialogue could not open. Check the local desktop session; no secret operation was authorised.')
    try:value=json.loads(result.stdout)
    except (ValueError,UnicodeError):raise ValueError('Invalid native passphrase response.') from None
    if not isinstance(value,str) or not value or len(value)>1024:raise ValueError('Enter a non-empty passphrase, up to 1024 characters.')
    return value

class MemoryCore:
    def __init__(self,root,chain,binary='/usr/bin/bitcoind'):
        from node_client import Core
        self.root=Path(root);self.root.mkdir(mode=0o700,parents=True);self.process=None
        if not Path(binary).is_file() or not os.access(binary,os.X_OK):raise LocalActionFailure('core_executable_missing','A usable Bitcoin Core bitcoind executable is required for protected wallet creation. Install a compatible native executable; no disk fallback was used.')
        with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as s:
            s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1);s.bind(('::1',0));port=s.getsockname()[1]
        args=[binary,'-datadir='+str(self.root),'-conf=/dev/null','-settings=0','-server=1','-listen=0','-connect=0','-dnsseed=0','-discover=0','-networkactive=0','-debuglogfile=0','-printtoconsole=1','-dbcache=16','-par=1','-rpcbind=[::1]','-rpcallowip=::1','-onlynet=ipv6','-rpcport='+str(port)]
        if chain!='main':args.append('-'+{'test':'testnet','signet':'signet','regtest':'regtest'}[chain])
        from core_startup import StartupOutput
        try:self.process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        except OSError as error:raise LocalActionFailure('core_execute_failed','The offline Core executable could not be launched; operating system errno='+str(error.errno)+'. No wallet keys were created.') from None
        self.startup_output=StartupOutput(self.process.stdout)
        network={'main':'','test':'testnet3','signet':'signet','regtest':'regtest'}[chain]
        self.core=Core({'cookie':str(self.root/network/'.cookie'),'rpc_port':port})
        for _ in range(200):
            try:
                info=rpc(self.core,'getblockchaininfo')
                if info['chain']!=chain:raise ValueError('Protected Core network differs.')
                break
            except Exception:
                if self.process.poll() is not None:raise self.startup_output.failure(self.process.returncode) from None
                time.sleep(.05)
        else:
            self.close();raise LocalActionFailure('core_startup_rpc_timeout','The offline Core process did not make its loopback RPC ready within 10 seconds. No wallet keys were created.')
        self.startup_output.clear()
    def private_descriptors(self,name):
        """Internal offline-Core read. Never exposed through public RPC or bridge."""
        from node_client import http_json
        from urllib.parse import quote
        if not self.process or self.process.poll() is not None:raise ValueError('The offline signing workspace is unavailable.')
        cookie=Path(self.core.config['cookie'])
        if not cookie.resolve().is_relative_to(self.root.resolve()):raise ValueError('Offline Core credentials are outside its protected directory.')
        result=http_json(self.core.config['rpc_port'],'/wallet/'+quote(name,safe=''),{'jsonrpc':'2.0','id':'private-local-policy','method':'listdescriptors','params':[True]},auth=cookie.read_text().strip(),response_limit=1024*1024)
        if not isinstance(result,dict) or result.get('error') or not isinstance(result.get('result'),dict):raise ValueError('Offline Core could not read the unlocked signing policy. No private diagnostic was exported.')
        return result['result']['descriptors']
    def close(self):
        if self.process and self.process.poll() is None:
            try:rpc(self.core,'stop');self.process.wait(timeout=60)
            except Exception:raise ValueError('Protected Core has not finished closing. Keep the RAM workspace running; it was not killed.') from None
        if hasattr(self,'startup_output'):
            self.startup_output.thread.join(1);self.startup_output.clear()

class WalletSetup:
    def __init__(self,core,store,environment=None,enforce=None,binary='/usr/bin/bitcoind'):
        self.core=core;self.store=store;self.environment=environment or {};self.enforce=enforce or (lambda:None);self.binary=binary;self.sessions={};self.reviews={};self.disc_sessions={};self.burner=Burner(store.root/'disc-jobs',self.burn_complete)
    def own_identity(self):
        key=getattr(self.store,'identity_root',self.store.root)/'preview_identity.pub'
        if not key.exists():sign(self.store,{'purpose':'identity-initialisation','version':1})
        public=' '.join(key.read_text().split()[:2]);return {'public_key':public,'fingerprint':fingerprint(public)}
    def unlock_estimates(self,facts):
        from vault_time import estimates
        return estimates(self.core,[facts['height']],expected_chain=facts['chain'])
    def review(self,key):
        p=self.store.read()['pending'][key]['proposal'];proposal(p)
        if p['kind']=='wallet_setup':
            own=self.own_identity();roles=[{**r,'fingerprint':fingerprint(r['agent_key']),'local':r['agent_key']==own['public_key']} for r in p['cosigners']]
            facts={'name':p['name'],'chain':p['chain'],'threshold':p['threshold'],'total':len(roles),'height':p['height'],'roles':roles,'proposal_hash':digest(p),'identity':own,'requires_disc':any(r['local'] and r['storage']=='disc' for r in roles),'no_bypass':True}
            return {'kind':'wallet_setup','id':key,'setup':facts,'unlock_estimates':self.unlock_estimates(facts)}
        session=self.sessions.get(digest(p['proposal']))
        if not session:
            from activity_log import event
            event('setup.missing','Complete policy has no original RAM session · setup='+digest(p['proposal'])[:12]+' · live_setups='+str(len(self.sessions))+' · burn_jobs='+str(len(self.disc_sessions)))
            raise LocalActionFailure('setup_session_missing','This policy request has no original setup in this protected workspace. Do not approve participation again to recreate its keys. Cancel this setup in Dashboard and reconcile any installed wallets locally before starting a fresh setup. Other approved archive jobs are unaffected.')
        messages=[];roles={r['id']:r for r in p['proposal']['cosigners']}
        for envelope in p['contributions']:
            ident=envelope.get('message',{}).get('cosigner_id')
            if ident not in roles:raise ValueError('Unknown cosigner contribution.')
            messages.append(verify(self.store,envelope,roles[ident]['agent_key']))
        descs=policy(p['proposal'],messages)
        if descs!=[p['receive_descriptor'],p['change_descriptor']]:raise ValueError('Dashboard policy differs from the independently constructed threshold, keys, branches or mandatory height. There is no editable or alternative spending path.')
        for own in session['contributions']:
            if own['message'] not in messages:raise ValueError('A locally generated contribution was replaced.')
        samples=[]
        for branch,desc in enumerate(descs):
            canonical=rpc(self.core,'getdescriptorinfo',[desc])
            if canonical.get('hasprivatekeys') or not canonical.get('isrange'):raise ValueError('Core did not confirm a ranged public policy.')
            for index in (0,1,10):
                local=Descriptor.from_string(desc).derive(index).script_pubkey().address(NETWORKS[p['proposal']['chain']]);node=rpc(self.core,'deriveaddresses',[desc,[index,index]])
                if node!=[local]:raise ValueError('Independent address derivation differs from Core.')
                samples.append({'branch':'Receive' if branch==0 else 'Change','index':index,'address':local})
        facts={'proposal_hash':digest(p['proposal']),'policy_hash':digest({'proposal':p['proposal'],'receive_descriptor':descs[0],'change_descriptor':descs[1],'contributions':p['contributions']}),'receive_descriptor':descs[0],'change_descriptor':descs[1],'samples':samples,'threshold':p['proposal']['threshold'],'total':len(roles),'height':p['proposal']['height'],'roles':[{**r,'fingerprint':fingerprint(r['agent_key']),'local':r['agent_key']==self.own_identity()['public_key']} for r in roles.values()],'name':p['proposal']['name'],'chain':p['proposal']['chain'],'requires_disc':any(r['agent_key']==self.own_identity()['public_key'] and r['storage']=='disc' for r in roles.values())}
        self.reviews[key]=(facts,time.time());return {'kind':'wallet_setup_policy','id':key,'setup':facts,'unlock_estimates':self.unlock_estimates(facts)}
    def check_cancel(self,binding):
        if binding in self.store.read().get('cancelled_setups',{}):raise ValueError('Dashboard requested cancellation. Review Delete and Cancel or Backup and Cancel on Authorise before continuing.')
    def approve_proposal(self,key,pins):
        self.enforce();row=self.store.read()['pending'][key];p=proposal(row['proposal']);own=self.own_identity()
        if rpc(self.core,'getblockchaininfo')['chain']!=p['chain']:raise ValueError('The proposed network differs from this local node.')
        identities={r['agent_key'] for r in p['cosigners']}
        expected={fingerprint(key) for key in identities}
        # Current UI enters each distinct producer once. Accept exact legacy role
        # maps only when every role still matches its full independent fingerprint.
        if p['kind']!='wallet_setup' or row['state']!='pending' or not isinstance(pins,dict):raise ValueError('Review and independently verify every distinct producing Agent.')
        if set(pins)==expected:
            if any(pins[f]!=f for f in expected):raise ValueError('An independently entered Agent fingerprint does not match.')
        elif set(pins)=={r['id'] for r in p['cosigners']}:
            if any(pins[r['id']]!=fingerprint(r['agent_key']) for r in p['cosigners']):raise ValueError('An independently entered Agent fingerprint does not match.')
        else:raise ValueError('Verify each distinct producing Agent in this exact wallet setup.')
        from combined_wallet import wallet_name
        local_roles=[r for r in p['cosigners'] if r['agent_key']==own['public_key'] and r['storage']=='node']
        planned=[wallet_name(p,r) for r in local_roles] or [wallet_name(p)]
        if len(set(planned))!=len(planned):raise ValueError('Use distinct local signing-role names before generating keys.')
        if {w['name'] for w in rpc(self.core,'listwalletdir')['wallets']}.intersection(planned):raise ValueError('A requested Core wallet name already exists. Existing wallets were retained; no signing keys were generated.')
        if any(session['phase'] not in ('complete','awaiting_disc') for session in self.sessions.values()):raise ValueError('Finish the current wallet setup and its physical backups before starting another wallet.')
        binding=digest(p);self.check_cancel(binding)
        if binding in self.sessions:raise ValueError('This setup already generated keys. No secret generation was repeated.')
        # Before generating anything, reserve this immutable session and mark attempted.
        with self.store.edit() as s:s['pending'][key]['state']='attempted';s['setup_active']=binding
        session={'created_at':int(time.time()),'proposal':p,'installed_wallets':{},'contributions':[],'wallets':{},'core':None,'phase':'generating','pins':dict(pins)};self.sessions[binding]=session
        stage='offline_core_start'
        try:
            local=[r for r in p['cosigners'] if r['agent_key']==own['public_key']]
            if local:session['core']=MemoryCore(self.store.root/'setup-cores'/binding,p['chain'],self.binary)
            for role in local:
                self.check_cancel(binding)
                stage='passphrase_entry'
                password=secret_dialog('Create a passphrase for signing role: '+role['name']+'\nWallet: '+p['name']+'\nSigner ID: '+role['id']+'\nThis creates encrypted signing keys only; it does not fund the wallet.',self.environment,confirm=True)
                if len(password)<12:raise ValueError('Use at least 12 characters for the encrypted signing wallet.')
                name='key_'+hashlib.sha256(role['id'].encode()).hexdigest()[:20];c=session['core'].core
                self.check_cancel(binding)
                stage='encrypted_wallet_creation'
                try:rpc(c,'createwallet',{'wallet_name':name,'passphrase':password,'descriptors':True,'load_on_startup':False})
                finally:password=None
                if rpc(c,'getwalletinfo',[],name).get('unlocked_until')!=0:raise ValueError('New signing wallet must be encrypted and locked.')
                stage='public_contribution'
                rows=rpc(c,'listdescriptors',[False],name)['descriptors'];branch={}
                for internal in (False,True):
                    match=[r['desc'].split('#')[0][5:-1] for r in rows if r.get('active') and r.get('internal',False)==internal and r['desc'].startswith('wpkh(')]
                    if len(match)!=1:raise ValueError('Core did not return one public BIP84 key per branch.')
                    branch[internal]=match[0]
                message={'session_id':p['session_id'],'proposal_hash':binding,'cosigner_id':role['id'],'receive_key':branch[False],'change_key':branch[True]};from setup_policy import public_key
                public_key(branch[False],0,p['chain']);public_key(branch[True],1,p['chain'])
                envelope=sign(self.store,message);session['contributions'].append(envelope);session['wallets'][role['id']]={'name':name,'storage':role['storage']}
                self.store.queue('wallet_setup_contribution',envelope)
            session['phase']='contributed';self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'session_id':p['session_id'],'proposal_hash':binding,'status':'participating'}))
            with self.store.edit() as s:s['pending'].pop(key,None);s['completed'][key]={'kind':'wallet_setup','at':time.time()}
            return {'message':'Participation complete · wallet creation moves no Bitcoin. Public contributions queued. Private keys remain in encrypted wallets inside protected RAM. Keep this workspace running until the complete policy is approved and all assigned backups are verified.'}
        except Exception as error:
            session['phase']='error'
            from activity_log import event
            from diagnostics import action_code,action_detail
            event('setup.failure','stage='+stage+' · '+action_code(error)+' · '+action_detail(error))
            raise
    def approve_policy(self,key):
        self.enforce();old=self.reviews.get(key)
        if not old or time.time()-old[1]>600:raise ValueError('Review the complete public policy again.')
        fresh=self.review(key)['setup']
        if fresh!=old[0]:raise ValueError('Complete policy changed. Review again.')
        p=self.store.read()['pending'][key]['proposal'];session=self.sessions[fresh['proposal_hash']];self.check_cancel(fresh['proposal_hash'])
        if session['phase']!='contributed':raise ValueError('Setup already attempted. Inspect local outcome; nothing was replayed.')
        from combined_wallet import wallet_name,role_wallet,public_policy,LAYOUT
        roles={r['id']:r for r in session['proposal']['cosigners']}
        targets={ident:wallet_name(session['proposal'],roles[ident]) for ident,row in session['wallets'].items() if row['storage']=='node'}
        monitor=next(iter(targets.values()),wallet_name(session['proposal']))
        planned=list(targets.values()) or [monitor]
        if len(set(planned))!=len(planned):raise ValueError('Signing roles produce duplicate wallet names. Choose distinct role names; no wallet was installed.')
        existing={w['name'] for w in rpc(self.core,'listwalletdir')['wallets']}
        if existing.intersection(planned):raise ValueError('A requested Core wallet name already exists. No existing wallet was replaced or renamed.')
        with self.store.edit() as s:s['pending'][key]['state']='attempted'
        session.update(phase='installing',policy=p,review=fresh)
        try:
            local={};disc={}
            # All production names are checked before requesting any additional secret.
            for ident,row in session['wallets'].items():
                self.check_cancel(fresh['proposal_hash'])
                if row['storage']=='disc':
                    combined=role_wallet(self,session,roles[ident],fresh)
                    path=self.store.root/'setup-cores'/fresh['proposal_hash']/(hashlib.sha256(ident.encode()).hexdigest()+'.dat')
                    rpc(session['core'].core,'backupwallet',[str(path)],combined)
                    disc[hashlib.sha256(ident.encode()).hexdigest()]=str(path)
                else:
                    target=targets[ident]
                    session.setdefault('installed_wallets',{})[target]=public_policy(fresh)
                    role_wallet(self,session,roles[ident],fresh,destination=self.core,target=target)
                    info=rpc(self.core,'getwalletinfo',[],target)
                    if not info.get('private_keys_enabled') or info.get('unlocked_until')!=0:raise ValueError('Persistent signer failed encrypted/locked verification.')
                    from build8_policy import descriptors
                    if descriptors(rpc(self.core,'listdescriptors',[False],target))!=descriptors(public_policy(fresh)):raise ValueError('Persistent signing wallet differs from the approved full policy.')
                    local[ident]=target
            self.check_cancel(fresh['proposal_hash'])
            if not local:
                # A machine producing only physical keys still needs a named public
                # wallet. Machines with node keys use that same wallet for monitoring.
                session.setdefault('installed_wallets',{})[monitor]=None
                rpc(self.core,'createwallet',{'wallet_name':monitor,'disable_private_keys':True,'blank':True,'descriptors':True,'load_on_startup':True})
                requests=[{'desc':fresh[field],'timestamp':session['created_at'],'active':True,'internal':bool(i),'range':[0,999]} for i,field in enumerate(('receive_descriptor','change_descriptor'))]
                result=rpc(self.core,'importdescriptors',{'requests':requests},monitor,timeout=86400)
                if not all(r.get('success') for r in result):raise ValueError('Core could not install the approved public policy.')
                session['installed_wallets'][monitor]=rpc(self.core,'listdescriptors',[False],monitor)
            recovery={'version':1,'wallet_layout':LAYOUT,'proposal':p['proposal'],'policy_hash':fresh['policy_hash'],'receive_descriptor':fresh['receive_descriptor'],'change_descriptor':fresh['change_descriptor'],'contributions':p['contributions'],'local_cosigners':list(session['wallets'])}
            with self.store.edit() as s:
                s.setdefault('approved_wallets',{})[fresh['policy_hash']]={**recovery,'monitor_wallet':monitor,'signing_wallets':local,'height':fresh['height'],'created':time.time()}
                s['completed'][key]={'kind':'wallet_setup_policy','at':time.time()};s['pending'].pop(key,None)
            from setup_completion import mark
            mark(self.core,self.store.read()['approved_wallets'][fresh['policy_hash']],False)
            session['phase']='awaiting_disc' if disc else 'complete'
            self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'session_id':p['proposal']['session_id'],'proposal_hash':fresh['proposal_hash'],'policy_hash':fresh['policy_hash'],'status':'policy_approved','backup':'pending' if disc else 'not_required'}))
            self.store.queue('wallet_setup_inventory',sign(self.store,{'version':1,'session_id':p['proposal']['session_id'],'policy_hash':fresh['policy_hash'],'chain':p['proposal']['chain'],'monitor_wallet':monitor,'signing_wallets':local,'receive_descriptor':fresh['receive_descriptor'],'change_descriptor':fresh['change_descriptor']}))
            with self.store.edit() as saved:
                if saved.get('setup_active')==fresh['proposal_hash']:saved.pop('setup_active',None)
            if disc:
                session['discs_remaining']=set(disc)
                for ident,path in sorted(disc.items()):
                    job_id=fresh['proposal_hash']+'-'+ident[:12];self.disc_sessions[job_id]=(fresh['proposal_hash'],ident)
                    self.burner.queue(job_id,{ident:path},{**recovery,'physical_cosigner_file':ident,'local_cosigners':[role['id'] for role in p['proposal']['cosigners'] if hashlib.sha256(role['id'].encode()).hexdigest()==ident]})
            else:self.finish_session(session)
            return {'message':'Exact policy approved. Each node signer stores its encrypted key and complete policy in one named Core wallet.'+(' Disc Operations is now available. Private-only disc keys remain in protected RAM.' if disc else ' Encrypted local signing wallets installed.'),'burn_authorised':bool(disc)}
        except Exception as error:
            session['phase']='installation_failed'
            from activity_log import event
            from diagnostics import action_code,action_detail
            event('setup.installation','Installation failed · '+action_code(error)+' · '+action_detail(error)+' · keys retained in protected RAM; no automatic retry')
            raise
    def burn_complete(self,ident,sha):
        if ident not in self.disc_sessions:
            if not getattr(self,'external_burn_complete',None):raise ValueError('Unknown external archive completion.')
            return self.external_burn_complete(ident,sha)
        from archive_inventory import initial
        initial(self.store,self.burner.job,sha)
        binding,cosigner=self.disc_sessions[ident];session=self.sessions[binding];review=session['review']
        self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'session_id':session['proposal']['session_id'],'proposal_hash':binding,'policy_hash':review['policy_hash'],'status':'backup_verified','cosigner_file':cosigner,'image_sha256':sha}))
        session['discs_remaining'].remove(cosigner)
        if not session['discs_remaining']:self.finish_session(session)
    def finish_session(self,session):
        if session.get('core'):session['core'].close();shutil.rmtree(session['core'].root)
        session['phase']='complete'
        with self.store.edit() as saved:
            if saved.get('setup_active')==digest(session['proposal']):saved.pop('setup_active',None)
    def decline(self,key):
        p=self.store.read()['pending'][key]['proposal'];binding=digest(p if p['kind']=='wallet_setup' else p['proposal']);self.check_cancel(binding);session=self.sessions.get(binding)
        if session:
            if session['phase']!='contributed':raise ValueError('Wallet installation was attempted. Reconcile the local outcome before discarding anything.')
            self.finish_session(session)
        self.store.deny(key)
        self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'proposal_hash':binding,'status':'denied'}))
    def cancel(self,binding):
        self.check_cancel(binding)
        session=self.sessions.get(binding)
        if not session or session['phase'] not in ('contributed','error'):raise ValueError('Only an unfinished setup before policy installation can be discarded. Reconcile any attempted installation locally.')
        env={**os.environ,**self.environment}
        prompt='Discard the temporary keys for '+session['proposal']['name']+'? This cannot be undone. Do not discard if this unfinished setup has been funded.'
        command=['/usr/bin/kdialog','--warningyesno',prompt] if shutil.which('kdialog') else ['/usr/bin/zenity','--question','--text='+prompt]
        if subprocess.run(command,env=env,capture_output=True,timeout=180).returncode:raise ValueError('Temporary keys retained.')
        self.finish_session(session)
        self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'proposal_hash':binding,'status':'denied'}))
        return {'message':'Unfinished temporary keys discarded after local confirmation. Start again with a fresh setup session.'}
    def burn(self,device,confirmed,disc_count=1,speed='slowest',job_id=None,selected_ids=None):
        if job_id is not None:
            if not self.burner.job or self.burner.job['id']!=job_id:raise ValueError('The disc job changed. Review its wallet selection again before burning.')
            if self.burner.job['phase']=='authorised':self.burner.select(selected_ids,job_id)
            elif selected_ids!=[i for i,w,r in self.burner.job.get('_members') or [(self.burner.job['id'],None,None)]]:raise ValueError('The prepared disc wallet selection cannot be changed.')
        self.enforce();self.burner.validate_options(device,confirmed,disc_count,speed)
        password=None
        if not self.burner.job.get('_prepared'):password=secret_dialog('Disc-backup passphrase · encrypt the complete recovery package (not your Core wallet passphrase)',self.environment,confirm=True)
        try:return self.burner.start(device,confirmed,password,disc_count,speed)
        finally:password=None
