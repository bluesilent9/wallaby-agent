"""Locally authorised history recovery. No backups or Wallet Server-controlled commands.

Jobs are durable before a mutation. An interrupted operation is inspected, never
silently replayed. Reindex flags are one-shot arguments, never bitcoin.conf edits.
"""
import fcntl,os,pwd,subprocess,threading,time
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc,sats

TERMINAL={'complete','error','interrupted','clone_paused'}

class ClonePaused(Exception):pass


def persistent_wallets(core):
    # Restored optical accounts run in a deliberately chainless RAM Core. They
    # are public signing routes, never wallets requiring the persistent node's
    # historical replay or restart plan.
    names=rpc(core,'listwallets')
    import node_client
    archive=node_client.LOCAL_ROUTER
    if archive is not None and core.config==archive.core.config:
        with archive.lock:virtual={name for record in archive.loaded.values() for name in record['routes']}
        names=[name for name in names if name not in virtual]
    return names

def history_missing(core,timestamp):
    chain=rpc(core,'getblockchaininfo')
    if not chain.get('pruned') or not chain.get('pruneheight'):return False
    floor=rpc(core,'getblockheader',[rpc(core,'getblockhash',[chain['pruneheight']])])
    return timestamp-7200 < floor['time']


def staging_timestamp(core):
    # Do not run even a two-hour import rescan when history is known missing.
    # The signed original timestamps remain in the job and are restored before replay.
    tip=rpc(core,'getblockheader',[rpc(core,'getbestblockhash')])
    return max(int(time.time()),tip['time'])+14401


def earliest(details):
    values=[r.get('timestamp',0) for r in details['public_wallet']['descriptors']]
    values += [v['timestamp'] for v in details.get('vaults',[])]
    return min([v if type(v) is int else 0 for v in values] or [0])


def require(store,key,name,details,staged=None):
    with store.edit() as s:
        s.setdefault('history_jobs',{})[key]={'wallet':name,'details':details,'timestamp':earliest(details),'staged':str(staged) if staged else None,'at':time.time(),'state':'pending','expected_private_keys':bool(staged)}


def verify_history(core,name,details,store):
    from public_policy import descriptors
    from wallet_ops import install_vault
    from wallet_labels import apply_labels
    apply_labels(core,name,details.get('address_labels',[]),write=False)
    if descriptors(rpc(core,'listdescriptors',[False],name))!=descriptors(details['public_wallet']):raise ValueError('Recovered wallet descriptor identity changed.')
    names=[name]
    for v in details.get('vaults',[]):
        from wallet_ops import verify_vault,watch_name
        known=store.read()['vaults'].get(digest(v));monitor=watch_name(v)
        if known and known.get('public')==v and monitor in rpc(core,'listwallets'):
            verify_vault(core,v);address=rpc(core,'getaddressinfo',[v['address']],monitor)
            if not (address.get('ismine') or address.get('iswatchonly')):raise ValueError('Vault monitor is not tracking the approved address.')
            names.append(monitor)
        else:names.append(install_vault(core,v,store,owner=name)['monitor_wallet'])
    for wallet in names:
        info=rpc(core,'getwalletinfo',[],wallet)
        if info.get('scanning'):raise ValueError('Wallet history is still scanning.')
    for out in details['funded_outputs']:
        # Old previews may now contain spent coins: verify the recorded transaction
        # locally, rather than falsely declaring history recovered from a server claim.
        found=False;failures=[]
        for wallet in names:
            try:
                tx=rpc(core,'gettransaction',[out['txid'],True],wallet)
                decoded=rpc(core,'decoderawtransaction',[tx['hex']])
                output=decoded['vout'][out['vout']]
                if str(sats(output['value']))!=out['amount_sats'] or output['scriptPubKey'].get('address')!=out['address']:raise ValueError('Recovered transaction differs from the approved public preview.')
                coin=rpc(core,'gettxout',[out['txid'],out['vout'],True])
                if coin:
                    if str(sats(coin['value']))!=out['amount_sats'] or coin['scriptPubKey'].get('address')!=out['address']:raise ValueError('Local chain output differs from the approved preview.')
                else:
                    block=tx.get('blockhash')
                    if not block or tx.get('confirmations',0)<=0:raise ValueError('Transaction is neither in this node’s current UTXO set nor its confirmed chain.')
                    header=rpc(core,'getblockheader',[block])
                    if header.get('confirmations',0)<=0 or out['txid'] not in rpc(core,'getblock',[block,1])['tx']:raise ValueError('Wallet transaction is not confirmed in this node’s active blockchain.')
                found=True;break
            except ValueError as error:failures.append(wallet+': '+str(error))
        if not found:raise ValueError('This node cannot yet verify approved transaction '+out['txid']+': '+'; '.join(failures))


def pruning_identity(chain):
    return {key:chain.get(key) for key in ('pruned','automatic_pruning','prune_target_size')}


def process_launch(core):
    """Match an owned Core process holding this RPC cookie directory's .lock."""
    netdir=Path(core.config['cookie']).expanduser().resolve().parent
    lock=netdir/'.lock'
    if not lock.exists():raise ValueError('Cannot identify the Core data-directory lock. Restart Core manually; no shutdown was requested.')
    identity=lock.stat();matches=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            if proc.stat().st_uid!=os.getuid():continue
            exe=(proc/'exe').resolve(strict=True)
            if exe.name not in ('bitcoind','bitcoin-qt'):continue
            holds=any((st.st_dev,st.st_ino)==(identity.st_dev,identity.st_ino) for fd in (proc/'fd').iterdir() for st in [fd.stat()])
            if not holds:continue
            args=(proc/'cmdline').read_bytes().split(b'\0');args=[a.decode() for a in args if a]
            env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if b'=' in x)
            # A service supervisor could relaunch behind us. Never race a system service.
            group=(proc/'cgroup').read_text()
            if '.service' in group and ('/system.slice/' in group or '/user@' in group and '/app.slice/' not in group):raise ValueError('Core is managed by a service. Stop/restart its service manually using the displayed recovery options; Agent will not race the service manager.')
            if str(exe).startswith('/snap/'):
                if env.get('SNAP_NAME')!='bitcoin-core' or env.get('SNAP_INSTANCE_NAME','bitcoin-core')!='bitcoin-core':raise ValueError('Unknown Snap Core launcher. Restart it manually.')
                app='bitcoin-core.qt' if exe.name=='bitcoin-qt' else 'bitcoin-core.daemon'
                launcher=['/usr/bin/snap','run',app]
            else:launcher=[str(exe)]
            clean=[a for a in args[1:] if a.split('=',1)[0].lstrip('-') not in ('reindex','reindex-chainstate','daemon','daemonwait')]
            # Original argv, current directory and selected desktop environment stay private.
            desktop={k:v for k,v in env.items() if k in ('DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','HOME','LANG','QT_QPA_PLATFORM')}
            if str(exe).startswith('/snap/'):desktop['HOME']=pwd.getpwuid(os.getuid()).pw_dir
            matches.append({'pid':int(proc.name),'started':(proc/'stat').read_text().rsplit(')',1)[1].split()[19],'argv':launcher+clean,'cwd':str((proc/'cwd').resolve()),'env':desktop,'netdir':str(netdir),'executable':str(exe)})
        except (OSError,UnicodeError,IndexError):continue
    if len(matches)!=1:raise ValueError('Could not uniquely identify this user’s Core process and data directory. No shutdown was requested; restart Core manually with the displayed recovery options.')
    return matches[0]


def lock_released(netdir):
    try:
        with (Path(netdir)/'.lock').open('rb') as file:
            # Core holds an exclusive POSIX lock. A shared probe conflicts with
            # that writer and works on the protected service's read-only mount.
            # Never create/open this persistent file for writing just to inspect it.
            fcntl.lockf(file,fcntl.LOCK_SH|fcntl.LOCK_NB)
            fcntl.lockf(file,fcntl.LOCK_UN);return True
    except BlockingIOError:return False


class Recovery:
    def __init__(self,core,store):self.core=core;self.store=store;self.thread=None;self.lock=threading.Lock();self.cached=None;self.cache_at=0;self.restart_deadline=0;self.clone_pause=threading.Event();self.clone_paused=threading.Event()
    def request_clone_pause(self):
        with self.lock:
            self.clone_pause.set();self.clone_paused.clear()
            if not self.thread or not self.thread.is_alive():
                rpc(self.core,'setnetworkactive',[False])
                with self.store.edit() as s:s.setdefault('recovery',{}).update(state='clone_paused',message='History recovery paused for a locally approved trusted clone. Pending jobs and extinction approval were retained.')
                self.clone_paused.set();self.cache_at=0
        try:rpc(self.core,'setnetworkactive',[False],timeout=3)
        except Exception:pass # A planned restart may still be in progress; checkpoint pauses before peers resume.
        return {'message':'Pausing history recovery at a safe boundary. Internet download is being paused; pending jobs are retained.'}
    def clone_checkpoint(self):
        if not self.clone_pause.is_set():return
        rpc(self.core,'setnetworkactive',[False])
        self.update('clone_paused','History recovery paused for trusted cloning. Existing wallets, pending history jobs and extinction approval were retained.')
        self.clone_paused.set();raise ClonePaused()
    def state(self):
        if self.cached and time.monotonic()-self.cache_at<5:return self.cached
        saved=self.store.read();job=saved.get('recovery',{});requirements=saved.get('history_jobs',{})
        try:
            chain=rpc(self.core,'getblockchaininfo');loaded=persistent_wallets(self.core);info={n:rpc(self.core,'getwalletinfo',[],n) for n in loaded}
            scanning=any(v.get('scanning') for v in info.values())
            missing=any(not r.get('registered_for_replay') and history_missing(self.core,r['timestamp']) for r in requirements.values()) or any(v.get('lastprocessedblock',{}).get('height',chain['blocks'])<chain.get('pruneheight',0) for v in info.values())
            ibd=bool(chain.get('initialblockdownload') or chain.get('headers',chain['blocks'])>chain['blocks'])
            lagging=any(v.get('lastprocessedblock',{}).get('height',chain['blocks'])<chain['blocks'] for v in info.values())
            red=missing or ibd
            status='Requires Blockchain Download' if red else 'Requires Rescan' if requirements or scanning or lagging else 'Synchronised'
            message='Bitcoin Core is downloading or validating blocks.' if ibd else 'Required wallet history is outside the retained blocks.' if missing else 'Wallet history needs local verification.' if requirements or scanning or lagging else 'Loaded wallet histories are current with this node’s chain.'
            if job.get('state')=='clone_paused':
                status='Paused for trusted clone';red=False;message='History recovery is paused. Continue in Blockchain to review the trusted clone and complete Extinct history, or explicitly review a new local recovery plan.'
            if status=='Synchronised' and any(r['proposal'].get('kind')=='wallet_retire' and r['proposal'].get('phase')=='preserve' for r in saved['pending'].values()):
                status='Extinction review required';message='Core is caught up. Review the pending extinction to check complete archived history; the node tip alone does not prove legacy history coverage.'
            result={'title':'This Node','status':status,'colour':'red' if red else 'amber' if status in ('Requires Rescan','Extinction review required','Paused for trusted clone') else 'green','message':message,'blocks':chain['blocks'],'headers':chain.get('headers',chain['blocks']),'progress':chain.get('verificationprogress'),'wallets':len(loaded),'running':job.get('state') not in TERMINAL and bool(job),'job':{k:v for k,v in job.items() if k in ('state','message','started','finished')},'can_refresh':status not in ('Synchronised','Extinction review required') and not scanning,'available':True}
        except Exception:result={'title':'This Node','status':'Requires Blockchain Download','colour':'red','message':'Core is unavailable or starting. Reconnect local RPC to assess its history; this does not by itself mean blocks must be downloaded again.','available':False,'can_refresh':False,'running':bool(job) and job.get('state') not in TERMINAL,'job':{k:v for k,v in job.items() if k in ('state','message','started','finished')}}
        self.cached=result;self.cache_at=time.monotonic();return result
    def plan(self):
        self.cache_at=0;state=self.state()
        if not state['available']:raise ValueError('Connect local Bitcoin Core before planning recovery.')
        if state['status']=='Synchronised':raise ValueError('This node is already synchronised.')
        if state['running']:raise ValueError('A recovery is already in progress. Its current status is shown on This Node.')
        chain=rpc(self.core,'getblockchaininfo');jobs=self.store.read().get('history_jobs',{})
        missing=any(not r.get('registered_for_replay') and history_missing(self.core,r['timestamp']) for r in jobs.values())
        if chain.get('pruned'):
            missing=missing or any(rpc(self.core,'getwalletinfo',[],name).get('lastprocessedblock',{}).get('height',chain['blocks'])<chain.get('pruneheight',0) for name in persistent_wallets(self.core))
        previous=self.store.read().get('recovery',{})
        mode='download' if missing else 'monitor' if chain.get('initialblockdownload') or chain.get('headers',chain['blocks'])>chain['blocks'] else 'rescan'
        paused=False
        if previous.get('plan',{}).get('replay') and not previous.get('replay_ready'):
            paused=not rpc(self.core,'getnetworkinfo').get('networkactive',True)
            if paused:mode='resume'
        plan={'mode':mode,'requirements':digest(jobs),'chain':chain['chain'],'wallets':sorted(set(persistent_wallets(self.core))|{r['wallet'] for r in jobs.values()}),'created':time.time(),'core_binding':{'cookie':str(Path(self.core.config['cookie']).expanduser().resolve()),'rpc_port':self.core.config['rpc_port']},'pruning':pruning_identity(chain)}
        target=max(chain['blocks'],chain.get('headers',chain['blocks']),previous.get('plan',{}).get('target_height',0) if previous.get('plan',{}).get('replay') else 0)
        plan.update(target_height=target,replay=mode in ('download','resume'))
        if previous.get('plan',{}).get('replay') or 'restore_network_after' in previous.get('plan',{}):
            plan['restore_network_after']=previous['plan'].get('restore_network_after',previous['plan'].get('network_was_active',True))
            if previous.get('replay_ready') and not rpc(self.core,'getnetworkinfo')['networkactive']:plan['resume_network']=True
        if mode=='download':
            from recovery_checkpoint import capture
            plan['clone_checkpoint']=capture(self.core,self.store)
            launch=process_launch(self.core)
            manager=subprocess.run(['/usr/bin/systemctl','--user','show-environment'],capture_output=True,timeout=10)
            if manager.returncode:raise ValueError('The user service manager is unavailable. Core was not stopped. Restart it manually with -reindex -networkactive=0, keeping your existing prune setting, then reopen the Agent to prepare wallets before enabling network activity.')
            plan['launch']=launch
            plan['network_was_active']=bool(rpc(self.core,'getnetworkinfo')['networkactive']);plan['restore_network_after']=plan['network_was_active']
        elif mode=='resume':plan['network_was_active']=previous['plan'].get('network_was_active',True)
        if self.store.read().get('chain_sync',{}).get('mode')=='ssh_only':
            plan.update(ssh_only=True,restore_network_after=False,resume_network=False)
        key=digest(plan)
        with self.store.edit() as s:s['recovery_plan']={'id':key,'plan':plan}
        messages={
            'download':'Authorise a clean Core shutdown and restart with -reindex. Your existing pruning setting stays unchanged throughout. Network activity is paused only while the Agent loads received wallets, original descriptor history timestamps and vault monitors; then Core downloads and records wallet history while pruning old blocks normally. This can take days and substantial bandwidth, but does not require keeping the full chain on disk. No additional backups are created.',
            'resume':'Continue preparing wallets while Core network activity is paused, then resume the blockchain download with the same pruning settings. No new reindex or wallet restoration is blindly repeated.',
            'rescan':'Authorise restoring queued encrypted wallets and rescanning wallet history using retained blocks already on disk. Pruning settings stay unchanged. No additional backups are created.',
            'monitor':'Core is already downloading. The Agent will monitor the existing download with pruning unchanged. A wallet must be registered before the blocks it needs are pruned; otherwise a new locally authorised reindex may be required.'}
        if plan.get('ssh_only'):messages[mode]+=' SSH-only mode is selected: Internet peers remain paused after wallet registration. Start receiving blocks from your paired Agent when ready.'
        return {'id':key,'mode':mode,'wallets':plan['wallets'],'message':messages[mode],'pruning':plan['pruning']}

    def start(self,key):
        with self.lock:
            saved=self.store.read();p=saved.get('recovery_plan',{})
            if p.get('id')!=key or time.time()-p['plan']['created']>300 or p['plan']['requirements']!=digest(saved.get('history_jobs',{})):raise ValueError('Recovery plan changed or expired. Review again.')
            if saved.get('setup_active'):raise ValueError('Finish wallet setup and its physical backups before recovery.')
            if saved.get('sync_batch') or saved.get('active_transfer'):raise ValueError('Finish the direct wallet transfer before recovering history.')
            if self.thread and self.thread.is_alive():raise ValueError('Recovery is already running.')
            if saved.get('recovery',{}).get('state') not in TERMINAL|{None}:raise ValueError('Previous recovery is still active. Inspect its status before continuing.')
            plan=p['plan']
            if bool(plan.get('ssh_only'))!=(self.store.read().get('chain_sync',{}).get('mode')=='ssh_only'):raise ValueError('Blockchain source mode changed. Review a fresh recovery plan before restarting Core.')
            binding={'cookie':str(Path(self.core.config['cookie']).expanduser().resolve()),'rpc_port':self.core.config['rpc_port']}
            if plan.get('core_binding')!=binding or rpc(self.core,'getblockchaininfo')['chain']!=plan['chain']:raise ValueError('Core connection changed. Review a fresh recovery plan.')
            if pruning_identity(rpc(self.core,'getblockchaininfo'))!=plan['pruning']:raise ValueError('Core pruning settings changed. Review a fresh recovery plan.')
            if plan['mode']=='download' and process_launch(self.core)!=plan['launch']:raise ValueError('Core process changed. Review a fresh recovery plan.')
            with self.store.edit() as s:s['recovery']={'state':'starting','started':time.time(),'plan':plan,'message':'Locally authorised history recovery is starting.'};s.pop('recovery_plan',None)
            self.clone_pause.clear();self.clone_paused.clear()
            self.thread=threading.Thread(target=self.run,args=(plan,),daemon=True);self.thread.start();return {'ok':True}
    def update(self,state,message):
        with self.store.edit() as s:s['recovery'].update(state=state,message=message)
        self.cache_at=0
    def restart_window(self):
        # Only this live, locally authorised restart owns the longer Core grace.
        # A saved flag after a crash, Wallet Server input or a failed launch cannot
        # suppress the ordinary 15-second connection failure handling.
        return bool(self.restart_deadline and time.monotonic()<self.restart_deadline and self.thread and self.thread.is_alive())
    def launch_command(self,launch,args,unit,wait=False):
        command=['/usr/bin/systemd-run','--user','--quiet','--service-type=exec','--slice=app.slice','--unit='+unit,'--working-directory='+launch['cwd']]
        if wait:command+=['--wait','--collect']
        command+=['--setenv='+k+'='+v for k,v in launch['env'].items()]
        # The desktop user manager lives outside the protected service's mount
        # namespace. Do not make its ability to launch Core depend on opening a
        # log file in that private workspace. Core keeps its usual debug.log;
        # service launch failures are also available in the user's journal.
        return command+['--property=StandardOutput=journal','--property=StandardError=journal','--']+args
    def restart(self,launch,extra):
        try:return self.restart_checked(launch,extra)
        finally:self.restart_deadline=0
    def restart_checked(self,launch,extra):
        if any(arg.split('=',1)[0].lstrip('-')=='prune' for arg in extra):raise ValueError('Recovery cannot override pruning settings.')
        # Ensure the original process still owns the same lock. Never kill Core.
        current=process_launch(self.core)
        if current['pid']!=launch['pid'] or current['started']!=launch['started']:raise ValueError('Core process changed; automatic restart stopped.')
        chain=rpc(self.core,'getblockchaininfo')['chain']
        unit='wallaby-core-recovery-'+str(time.time_ns())
        # Exercise the SAME manager, cwd, environment and output configuration
        # before Core is touched. This catches namespace, permission and manager
        # failures which show-environment alone cannot detect.
        try:
            probe=subprocess.run(self.launch_command(launch,['/usr/bin/true'],unit+'-check',wait=True),capture_output=True,timeout=30)
        except (OSError,subprocess.TimeoutExpired):
            raise ValueError('The separate Core restart service could not be checked. Core was not stopped. Check the desktop user service manager before retrying.') from None
        if probe.returncode:raise ValueError('The separate Core restart service failed its launch check. Core was not stopped. Check the desktop user journal before retrying.')
        # Preserve the reviewed data/config arguments: a bare version probe can
        # otherwise consult a different default configuration. Core exits for
        # -version before acquiring its data-directory lock or opening wallets.
        probe_args=list(launch['argv'])+['-version']
        try:
            version_probe=subprocess.run(self.launch_command(launch,probe_args,unit+'-version-check',wait=True),capture_output=True,timeout=30)
        except (OSError,subprocess.TimeoutExpired):
            raise ValueError('The actual Core launcher could not complete its preflight. Core was not stopped. Check its Snap/desktop environment and user journal before retrying.') from None
        if version_probe.returncode:raise ValueError('The actual Core launcher failed its preflight. Core was not stopped. Check its Snap/desktop environment and user journal before retrying.')
        try:
            with (Path(launch['netdir'])/'.lock').open('rb'):pass
        except OSError:
            raise ValueError('Core data-directory lock could not be read before restart. Core was not stopped; check local read permissions.') from None
        self.restart_deadline=time.monotonic()+900
        with self.store.edit() as saved:saved['recovery']['restart_unit']=unit
        from activity_log import event
        event('history.restart','Independent service preflight passed; locally authorised Core restart · grace_seconds=900')
        self.update('stopping','Planned Bitcoin Core restart: waiting for a clean shutdown. The protected workspace stays open while Core restarts.')
        rpc(self.core,'stop')
        for _ in range(600):
            exited=not Path('/proc',str(launch['pid'])).exists()
            # A child process owned by this interpreter can remain a zombie until reaped.
            if not exited:
                try:exited=Path('/proc',str(launch['pid']),'stat').read_text().rsplit(')',1)[1].split()[0]=='Z'
                except FileNotFoundError:exited=True
            if exited:
                try:
                    if lock_released(launch['netdir']):break
                except OSError as error:
                    event('history.restart','Read-only shutdown lock check failed · errno='+str(error.errno))
                    raise ValueError('Core shut down, but its read-only data-directory lock check failed. No restart was launched. Keep the workspace open and inspect local permissions before starting Core manually.') from None
            time.sleep(.5)
        else:raise ValueError('Core has not finished shutting down. It was not killed or restarted.')
        # Separate user service: upgrading/restarting the Agent must never kill Core.
        # The RPC cookie directory's held lock was matched above; bind the restart
        # to that same data root even when Snap changes HOME while launching.
        netdir=Path(launch['netdir']);data_root=netdir if chain=='main' else netdir.parent
        args=list(launch['argv'])+['-datadir='+str(data_root)]+extra
        if Path(launch['executable']).name=='bitcoind':args.append('-daemon=0')
        command=self.launch_command(launch,args,unit)
        try:result=subprocess.run(command,capture_output=True,timeout=30)
        except (OSError,subprocess.TimeoutExpired):
            event('history.restart','Separate Core launch outcome uncertain; no duplicate launch requested')
            raise ValueError('Core shut down, but its separate restart service did not confirm startup. Check the user journal and Core debug.log before starting Core manually; no second launch was attempted.') from None
        if result.returncode:
            event('history.restart','Separate Core launch refused · exit_code='+str(result.returncode))
            raise ValueError('Core shut down cleanly, but its separate user service could not start. Check the user journal and Core debug.log. No duplicate Core was launched and history recovery has not completed.')
        event('history.restart','Separate Core service launched; waiting for local RPC readiness')
        self.update('starting','Core restart service launched. Waiting for local RPC; protected workspace retained.')
        ready=self.wait_rpc(startup_unit=unit)
        if ready['chain']!=chain:raise ValueError('Restarted Core is on a different chain. Recovery stopped; no wallet restoration was attempted.')
        event('history.restart','Local Core RPC ready; normal connection timeout restored')
        self.update('downloading','Core is responding. Preparing the reviewed blockchain recovery.')
    def wait_rpc(self,timeout=600,startup_unit=None):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:return rpc(self.core,'getblockchaininfo',timeout=5)
            except Exception:pass
            if startup_unit:
                try:
                    result=subprocess.run(['/usr/bin/systemctl','--user','show',startup_unit,'--property=ActiveState','--property=ExecMainStatus'],capture_output=True,text=True,timeout=3)
                    fields=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line) if result.returncode==0 and isinstance(result.stdout,str) else {}
                except (OSError,subprocess.TimeoutExpired):fields={}
                if fields.get('ActiveState') in ('failed','inactive'):
                    code=fields.get('ExecMainStatus','unknown');code=code if code.isdecimal() else 'unknown'
                    from activity_log import event
                    event('history.restart','Core service stopped before RPC readiness · exit_status='+code)
                    raise ValueError('The Core restart service stopped before RPC became ready (exit status '+code+'). Check its desktop user journal and Core debug.log. Recovery stopped without launching a second Core.')
            time.sleep(1)
        raise ValueError('Core did not become available. Check Core debug.log and the desktop user journal; the Agent will not launch duplicates.')
    def check_wallet(self,name,job):
        info=rpc(self.core,'getwalletinfo',[],name)
        if bool(info.get('private_keys_enabled'))!=job.get('expected_private_keys',bool(job.get('staged'))) or (job.get('staged') and ('unlocked_until' not in info or info['unlocked_until']!=0)):
            if job.get('staged'):rpc(self.core,'unloadwallet',{'wallet_name':name,'load_on_startup':False})
            raise ValueError('Recovered wallet failed private-key capability or encryption checks. Inspect Core before proceeding.')
    def restore_once(self,key,job):
        name=job['wallet']
        if name in persistent_wallets(self.core):return
        if not job.get('staged') and job.get('local_only'):
            # A locally reviewed existing wallet may not have been configured
            # for startup loading. Reload it after the authorised Core restart;
            # subsequent capability/descriptor checks still bind the exact job.
            rpc(self.core,'loadwallet',{'filename':name,'load_on_startup':True},timeout=86400)
            self.check_wallet(name,job)
            from public_policy import descriptors
            if descriptors(rpc(self.core,'listdescriptors',[False],name))!=descriptors(job['details']['public_wallet']):raise ValueError('Local recovery wallet identity changed. No history import was started.')
            return
        if not job.get('staged'):raise ValueError('The received public wallet is not loaded. Inspect Core before continuing recovery.')
        with self.store.edit() as saved:
            if saved['history_jobs'][key]['state']!='pending':raise ValueError('A previous restoration was attempted. Inspect/load that wallet in Core; restoration will not be repeated automatically.')
            saved['history_jobs'][key]['state']='attempted'
        rpc(self.core,'restorewallet',{'wallet_name':name,'backup_file':__import__('core_ram_path').for_core(self.core,job['staged']),'load_on_startup':True},timeout=86400)
    def register_watch_history(self,name,details):
        requests=[]
        for row in details['public_wallet']['descriptors']:
            request={k:v for k,v in row.items() if k in ('desc','timestamp','active','internal','range','next_index')}
            if 'next' in row:request['next_index']=row['next']
            requests.append(request)
        result=rpc(self.core,'importdescriptors',{'requests':requests},name,timeout=86400)
        if not result or len(result)!=len(requests) or not all(item.get('success') for item in result):raise ValueError('Core could not register the original descriptor history timestamps.')
        # Re-importing descriptors may reset their address-book labels in Core.
        # Restore only the exact labels from the locally approved public preview.
        from wallet_labels import apply_labels
        apply_labels(self.core,name,details.get('address_labels',[]),write=True)
        # Core 31 only connects birthday-change notifications for active
        # descriptors. Fixed addr() watches are inactive: reload the public
        # wallet so its in-memory birthday uses the restored history timestamps.
        if rpc(self.core,'getwalletinfo',[],name).get('private_keys_enabled'):raise ValueError('History registration requires a public-only wallet.')
        rpc(self.core,'unloadwallet',{'wallet_name':name,'load_on_startup':True})
        rpc(self.core,'loadwallet',{'filename':name,'load_on_startup':True},timeout=86400)
    def prepare_replay(self,plan):
        from wallet_ops import install_vault
        from wallet_labels import apply_labels
        from public_policy import descriptors
        chain=self.wait_rpc()
        if pruning_identity(chain)!=plan['pruning']:raise ValueError('Core restarted with different pruning settings. Network activity remains paused; no pruning option was changed by the Agent.')
        if rpc(self.core,'getnetworkinfo')['networkactive']:raise ValueError('Core network activity resumed before wallet preparation. Review a new recovery plan to avoid losing wallet history to pruning.')
        self.update('rescanning','Loading all approved wallets and vault descriptors before blockchain replay. Pruning stays unchanged.')
        jobs=self.store.read().get('history_jobs',{})
        for name in plan['wallets']:
            if name in persistent_wallets(self.core) or any(job['wallet']==name for job in jobs.values()):continue
            rpc(self.core,'loadwallet',{'filename':name},timeout=86400)
        for key,job in jobs.items():
            if history_missing(self.core,job['timestamp']):raise ValueError('Required blocks were already pruned before this wallet could be registered. Keep pruning unchanged and review a fresh reindex plan.')
            self.restore_once(key,job);name=job['wallet'];self.check_wallet(name,job)
            if descriptors(rpc(self.core,'listdescriptors',[False],name))!=descriptors(job['details']['public_wallet']):raise ValueError('Received wallet descriptor identity changed.')
            if not job.get('expected_private_keys'):self.register_watch_history(name,job['details'])
            apply_labels(self.core,name,job['details'].get('address_labels',[]),write=False)
            monitors=[]
            for vault in job['details'].get('vaults',[]):monitors.append(install_vault(self.core,vault,self.store,owner=name)['monitor_wallet'])
            with self.store.edit() as saved:
                saved['history_jobs'][key].update(registered_for_replay=True,monitor_wallets=monitors)
        with self.store.edit() as saved:saved['recovery']['replay_ready']=True
        self.clone_checkpoint()
        rpc(self.core,'setnetworkactive',[not plan.get('ssh_only',False)])
        self.update('downloading','Wallets and vaults are registered. Downloading and recording history while keeping the existing pruning settings.')
    def run(self,plan):
        try:
            self.clone_checkpoint()
            if plan['mode']=='download':self.restart(plan['launch'],['-reindex=1','-networkactive=0'])
            if plan.get('replay'):self.prepare_replay(plan)
            else:
                if plan.get('resume_network') and not plan.get('ssh_only'):rpc(self.core,'setnetworkactive',[True])
                self.update('downloading' if plan['mode']=='monitor' else 'rescanning','Waiting for the local blockchain and wallet histories. Pruning settings are unchanged.')
            while True:
                self.clone_checkpoint()
                chain=self.wait_rpc()
                self.clone_checkpoint()
                if plan.get('ssh_only') and self.store.read().get('chain_sync',{}).get('mode')=='ssh_only' and rpc(self.core,'getnetworkinfo')['networkactive']:rpc(self.core,'setnetworkactive',[False])
                if pruning_identity(chain)!=plan['pruning']:raise ValueError('Core pruning settings changed during recovery. Recovery stopped for local review.')
                if not chain.get('initialblockdownload') and chain.get('headers',chain['blocks'])==chain['blocks'] and chain['blocks']>=plan['target_height']:break
                self.clone_pause.wait(5)
            self.clone_checkpoint()
            processed=set()
            for key,job in self.store.read().get('history_jobs',{}).items():
                self.clone_checkpoint()
                name=job['wallet'];stage=job.get('staged')
                if job.get('registered_for_replay'):
                    # Core scanned these wallets as blocks arrived, before pruning.
                    for wallet in [name,*job.get('monitor_wallets',[])]:
                        info=rpc(self.core,'getwalletinfo',[],wallet)
                        if info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise ValueError('A replay wallet has not yet processed the current node tip. Recovery remains incomplete.')
                else:
                    if history_missing(self.core,job['timestamp']):raise ValueError('Wallet was not registered before its required blocks were pruned. Authorise a new reindex with pruning unchanged.')
                    self.restore_once(key,job)
                    self.update('rescanning','Rescanning '+name)
                    if not job.get('expected_private_keys'):self.register_watch_history(name,job['details'])
                    else:rpc(self.core,'rescanblockchain',[chain.get('pruneheight',-1)+1 if chain.get('pruned') else 0],name,timeout=86400)
                self.check_wallet(name,job)
                verify_history(self.core,name,job['details'],self.store);processed.add(name)
                if job.get('extinct_upgrade'):
                    if job['timestamp']!=0:raise ValueError('Whole Extinct migration requires complete historical coverage.')
                    from extinct_upgrade import certify
                    from wallet_labels import fixed_address
                    certify(self.core,self.store,name,[fixed_address(r['desc']) for r in job['details']['public_wallet']['descriptors']])
                from public_policy import descriptors
                with self.store.edit() as saved:saved.setdefault('history_coverage',{})[name]={'identity':digest(sorted(descriptors(job['details']['public_wallet']))),'from_time':job['timestamp'],'tip':chain['bestblockhash']}
                if not job.get('local_only'):self.store.queue('wallet_transfer_result',{'request_hash':key,'status':'complete','message':'Wallet and vault history verified; pruning settings were unchanged throughout recovery.'})
                with self.store.edit() as saved:
                    saved['history_jobs'].pop(key);saved['pending'].pop(key,None);saved['completed'][key]={'kind':'wallet_transfer','at':time.time()}
                if stage:Path(stage).unlink(missing_ok=True)
            if plan['mode']=='rescan':
                for name in plan['wallets']:
                    if name not in processed:rpc(self.core,'rescanblockchain',[max(chain.get('pruneheight',-1)+1,rpc(self.core,'getwalletinfo',[],name).get('lastprocessedblock',{}).get('height',0)) if chain.get('pruned') else 0],name,timeout=86400)
            for name in plan['wallets']:
                info=rpc(self.core,'getwalletinfo',[],name)
                if info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise ValueError('A wallet has not finished processing the recovered chain.')
            if plan.get('restore_network_after') is False and (not plan.get('ssh_only') or self.store.read().get('chain_sync',{}).get('mode')=='ssh_only'):rpc(self.core,'setnetworkactive',[False])
            # Only a local approval recorded for this exact pending proposal may
            # finish preservation. Coverage alone never grants deletion consent.
            from retirement_continuation import finish
            finish(self.core,self.store)
            self.update('complete','History recovery completed. Wallet and vault history is stored in Core. The original pruning settings were kept throughout.')
            with self.store.edit() as saved:saved['recovery']['finished']=time.time()
        except ClonePaused:return
        except Exception as error:
            from activity_log import event
            event('history.recovery','Stopped · exception='+type(error).__name__+(' · errno='+str(error.errno) if isinstance(error,OSError) else '')+' · state='+self.store.read().get('recovery',{}).get('state','unknown'))
            self.update('error',str(error) if isinstance(error,ValueError) else 'History recovery stopped with an uncertain result. Inspect Core debug.log and the desktop user journal. No wallet operation was automatically repeated and no pruning setting was changed.')
    def resume_monitor(self):
        # A UI-service restart cannot repeat shutdown, reindex, import or restore.
        job=self.store.read().get('recovery',{})
        if job and job.get('state') not in TERMINAL and not (self.thread and self.thread.is_alive()):self.update('interrupted','Agent restarted during recovery. Core may still be downloading. Check its state, then review a new local recovery plan; no operation was replayed.')
