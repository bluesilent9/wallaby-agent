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


def secret_dialog(prompt,environment,confirm=False):
    env={**os.environ,**environment};env['QT_LOGGING_RULES']='*.debug=false;*.info=false'
    def ask():
        if shutil.which('kdialog'):command=['/usr/bin/kdialog','--title','Wallaby Agent · protected local authorisation','--password',prompt]
        elif shutil.which('zenity'):command=['/usr/bin/zenity','--password','--title=Wallaby Agent · '+prompt]
        else:raise ValueError('Install kdialog or zenity. Secrets are never requested through the browser.')
        result=subprocess.run(command,capture_output=True,timeout=300,env=env)
        if result.returncode:raise ValueError('Local secret entry cancelled. No operation was authorised.')
        value=result.stdout.decode().rstrip('\n')
        if not value or len(value)>1024:raise ValueError('Enter a non-empty passphrase, up to 1024 characters.')
        return value
    value=ask()
    if confirm and ask()!=value:raise ValueError('Passphrases did not match.')
    return value

class MemoryCore:
    def __init__(self,root,chain,binary='/usr/bin/bitcoind'):
        from node_client import Core
        self.root=Path(root);self.root.mkdir(mode=0o700,parents=True);self.process=None
        if not Path(binary).is_file() or not os.access(binary,os.X_OK):raise ValueError('Install a native Bitcoin Core bitcoind executable. A confined Snap process cannot be silently substituted for the protected RAM node.')
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        args=[binary,'-datadir='+str(self.root),'-conf=/dev/null','-settings=0','-server=1','-listen=0','-connect=0','-dnsseed=0','-discover=0','-networkactive=0','-debuglogfile=0','-printtoconsole=0','-dbcache=16','-par=1','-rpcport='+str(port)]
        if chain!='main':args.append('-'+{'test':'testnet','signet':'signet','regtest':'regtest'}[chain])
        self.process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        network={'main':'','test':'testnet3','signet':'signet','regtest':'regtest'}[chain]
        self.core=Core({'cookie':str(self.root/network/'.cookie'),'rpc_port':port})
        for _ in range(200):
            try:
                info=rpc(self.core,'getblockchaininfo')
                if info['chain']!=chain:raise ValueError('Protected Core network differs.')
                break
            except Exception:
                if self.process.poll() is not None:raise ValueError('Protected RAM Core failed to start. Inspect its installation; no disk fallback is permitted.') from None
                time.sleep(.05)
        else:self.close();raise ValueError('Protected RAM Core RPC did not become ready.')
    def close(self):
        if self.process and self.process.poll() is None:
            try:rpc(self.core,'stop');self.process.wait(timeout=60)
            except Exception:raise ValueError('Protected Core has not finished closing. Keep the RAM workspace running; it was not killed.') from None

class WalletSetup:
    def __init__(self,core,store,environment=None,enforce=None,binary='/usr/bin/bitcoind'):
        self.core=core;self.store=store;self.environment=environment or {};self.enforce=enforce or (lambda:None);self.binary=binary;self.sessions={};self.reviews={};self.disc_sessions={};self.burner=Burner(store.root/'disc-jobs',self.burn_complete)
    def own_identity(self):
        key=getattr(self.store,'identity_root',self.store.root)/'preview_identity.pub'
        if not key.exists():sign(self.store,{'purpose':'identity-initialisation','version':1})
        public=' '.join(key.read_text().split()[:2]);return {'public_key':public,'fingerprint':fingerprint(public)}
    def review(self,key):
        p=self.store.read()['pending'][key]['proposal'];proposal(p)
        if p['kind']=='wallet_setup':
            own=self.own_identity();roles=[{**r,'fingerprint':fingerprint(r['agent_key']),'local':r['agent_key']==own['public_key']} for r in p['cosigners']]
            facts={'name':p['name'],'chain':p['chain'],'threshold':p['threshold'],'total':len(roles),'height':p['height'],'roles':roles,'proposal_hash':digest(p),'identity':own,'requires_disc':any(r['local'] and r['storage']=='disc' for r in roles),'no_bypass':True}
            return {'kind':'wallet_setup','id':key,'setup':facts}
        session=self.sessions.get(digest(p['proposal']))
        if not session:raise ValueError('Approve this exact participation proposal locally before reviewing its complete policy. A RAM workspace restart requires a fresh setup session.')
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
        self.reviews[key]=(facts,time.time());return {'kind':'wallet_setup_policy','id':key,'setup':facts}
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
        if any(session['phase']!='complete' for session in self.sessions.values()):raise ValueError('Finish the current wallet setup and its physical backups before starting another wallet.')
        binding=digest(p)
        if binding in self.sessions:raise ValueError('This setup already generated keys. No secret generation was repeated.')
        # Before generating anything, reserve this immutable session and mark attempted.
        with self.store.edit() as s:s['pending'][key]['state']='attempted';s['setup_active']=binding
        session={'proposal':p,'contributions':[],'wallets':{},'core':None,'phase':'generating','pins':dict(pins)};self.sessions[binding]=session
        try:
            local=[r for r in p['cosigners'] if r['agent_key']==own['public_key']]
            if local:session['core']=MemoryCore(self.store.root/'setup-cores'/binding,p['chain'],self.binary)
            for role in local:
                name='key_'+hashlib.sha256(role['id'].encode()).hexdigest()[:20]
                password=secret_dialog('Create encrypted Bitcoin Core signing wallet '+name+' · role '+role['id']+'\nThis creates keys only; it does not fund the wallet.',self.environment,confirm=True)
                if len(password)<12:raise ValueError('Use at least 12 characters for the encrypted signing wallet.')
                name='key_'+hashlib.sha256(role['id'].encode()).hexdigest()[:20];c=session['core'].core
                try:rpc(c,'createwallet',{'wallet_name':name,'passphrase':password,'descriptors':True,'load_on_startup':False})
                finally:password=None
                if rpc(c,'getwalletinfo',[],name).get('unlocked_until')!=0:raise ValueError('New signing wallet must be encrypted and locked.')
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
        except Exception:session['phase']='error';raise
    def approve_policy(self,key):
        self.enforce();old=self.reviews.get(key)
        if not old or time.time()-old[1]>600:raise ValueError('Review the complete public policy again.')
        fresh=self.review(key)['setup']
        if fresh!=old[0]:raise ValueError('Complete policy changed. Review again.')
        p=self.store.read()['pending'][key]['proposal'];session=self.sessions[fresh['proposal_hash']]
        if session['phase']!='contributed':raise ValueError('Setup already attempted. Inspect local outcome; nothing was replayed.')
        with self.store.edit() as s:s['pending'][key]['state']='attempted'
        session.update(phase='installing',policy=p,review=fresh)
        local={};disc={}
        for ident,row in session['wallets'].items():
            path=self.store.root/'setup-cores'/fresh['proposal_hash']/(hashlib.sha256(ident.encode()).hexdigest()+'.dat');rpc(session['core'].core,'backupwallet',[str(path)],row['name'])
            if row['storage']=='disc':disc[hashlib.sha256(ident.encode()).hexdigest()]=str(path)
            else:
                target='Wallaby key '+fresh['proposal_hash'][:12]+' '+hashlib.sha256(ident.encode()).hexdigest()[:8]
                rpc(self.core,'restorewallet',{'wallet_name':target,'backup_file':__import__('core_ram_path').for_core(self.core,path),'load_on_startup':True},timeout=86400)
                info=rpc(self.core,'getwalletinfo',[],target)
                if not info.get('private_keys_enabled') or info.get('unlocked_until')!=0:raise ValueError('Persistent signer failed encrypted/locked verification.')
                local[ident]=target;path.unlink()
        monitor='Wallaby policy '+fresh['policy_hash'][:20]
        rpc(self.core,'createwallet',{'wallet_name':monitor,'disable_private_keys':True,'blank':True,'descriptors':True,'load_on_startup':True})
        requests=[{'desc':fresh[field],'timestamp':'now','active':True,'internal':bool(i),'range':[0,999]} for i,field in enumerate(('receive_descriptor','change_descriptor'))]
        result=rpc(self.core,'importdescriptors',{'requests':requests},monitor,timeout=86400)
        if not all(r.get('success') for r in result):raise ValueError('Core could not install the approved public policy.')
        recovery={'version':1,'proposal':p['proposal'],'policy_hash':fresh['policy_hash'],'receive_descriptor':fresh['receive_descriptor'],'change_descriptor':fresh['change_descriptor'],'contributions':p['contributions'],'local_cosigners':list(session['wallets'])}
        with self.store.edit() as s:
            s.setdefault('approved_wallets',{})[fresh['policy_hash']]={**recovery,'monitor_wallet':monitor,'signing_wallets':local,'height':fresh['height'],'created':time.time()}
            s['completed'][key]={'kind':'wallet_setup_policy','at':time.time()};s['pending'].pop(key,None)
        from setup_completion import mark
        mark(self.core,self.store.read()['approved_wallets'][fresh['policy_hash']],False)
        session['phase']='awaiting_disc' if disc else 'complete'
        self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'session_id':p['proposal']['session_id'],'proposal_hash':fresh['proposal_hash'],'policy_hash':fresh['policy_hash'],'status':'policy_approved','backup':'pending' if disc else 'not_required'}))
        self.store.queue('wallet_setup_inventory',sign(self.store,{'version':1,'session_id':p['proposal']['session_id'],'policy_hash':fresh['policy_hash'],'chain':p['proposal']['chain'],'monitor_wallet':monitor,'signing_wallets':local,'receive_descriptor':fresh['receive_descriptor'],'change_descriptor':fresh['change_descriptor']}))
        if disc:
            session['discs_remaining']=set(disc)
            for ident,path in sorted(disc.items()):
                job_id=fresh['proposal_hash']+'-'+ident[:12];self.disc_sessions[job_id]=(fresh['proposal_hash'],ident)
                self.burner.queue(job_id,{ident:path},{**recovery,'physical_cosigner_file':ident,'local_cosigners':[role['id'] for role in p['proposal']['cosigners'] if hashlib.sha256(role['id'].encode()).hexdigest()==ident]})
        else:self.finish_session(session)
        return {'message':'Exact policy approved and public monitor installed.'+(' Disc Operations is now available. Private-only disc keys remain in protected RAM.' if disc else ' Encrypted local signing wallets installed.'),'burn_authorised':bool(disc)}
    def burn_complete(self,ident,sha):
        binding,cosigner=self.disc_sessions[ident];session=self.sessions[binding];review=session['review']
        self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'session_id':session['proposal']['session_id'],'proposal_hash':binding,'policy_hash':review['policy_hash'],'status':'backup_verified','cosigner_file':cosigner,'image_sha256':sha}))
        session['discs_remaining'].remove(cosigner)
        if not session['discs_remaining']:self.finish_session(session)
    def finish_session(self,session):
        if session.get('core'):session['core'].close();shutil.rmtree(session['core'].root)
        session['phase']='complete'
        with self.store.edit() as saved:saved.pop('setup_active',None)
    def decline(self,key):
        p=self.store.read()['pending'][key]['proposal'];binding=digest(p if p['kind']=='wallet_setup' else p['proposal']);session=self.sessions.get(binding)
        if session:
            if session['phase']!='contributed':raise ValueError('Wallet installation was attempted. Reconcile the local outcome before discarding anything.')
            self.finish_session(session)
        self.store.deny(key)
        self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'proposal_hash':binding,'status':'denied'}))
    def cancel(self,binding):
        session=self.sessions.get(binding)
        if not session or session['phase'] not in ('contributed','error'):raise ValueError('Only an unfinished setup before policy installation can be discarded. Reconcile any attempted installation locally.')
        env={**os.environ,**self.environment}
        prompt='Discard the temporary keys for '+session['proposal']['name']+'? This cannot be undone. Do not discard if this unfinished setup has been funded.'
        command=['/usr/bin/kdialog','--warningyesno',prompt] if shutil.which('kdialog') else ['/usr/bin/zenity','--question','--text='+prompt]
        if subprocess.run(command,env=env,capture_output=True,timeout=180).returncode:raise ValueError('Temporary keys retained.')
        self.finish_session(session)
        self.store.queue('wallet_setup_ack',sign(self.store,{'version':1,'proposal_hash':binding,'status':'denied'}))
        return {'message':'Unfinished temporary keys discarded after local confirmation. Start again with a fresh setup session.'}
    def burn(self,device,confirmed,disc_count=1,speed='slowest'):
        self.enforce();self.burner.validate_options(device,confirmed,disc_count,speed)
        password=None
        if not self.burner.job.get('_prepared'):password=secret_dialog('Disc-backup passphrase · encrypt the complete recovery package (not your Core wallet passphrase)',self.environment,confirm=True)
        try:return self.burner.start(device,confirmed,password,disc_count,speed)
        finally:password=None
