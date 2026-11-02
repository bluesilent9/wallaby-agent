"""One node/window lifecycle, controlled outside the protected signing worker.

Only public lifecycle flags cross this boundary. Cleanup uses the existing fixed
system service and retains its protections if unfinished work prevents closing.
"""
import contextlib,fcntl,threading,time

@contextlib.contextmanager
def control_lock(blocking=True):
    from runtime import runtime_dir
    with (runtime_dir()/'node-control.lock').open('a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False;return
        try:yield True
        finally:fcntl.flock(stream,fcntl.LOCK_UN)

def closing():
    from runtime import runtime_dir
    return (runtime_dir()/'workspace-closing').exists()

class Lifecycle:
    def __init__(self):self.thread=None;self.retry_after=0;self.legacy_view_seen=False;self.cleanup_wait_until=0
    def poll(self):
        from protected_memory import required
        if not required() or self.thread and self.thread.is_alive() or time.monotonic()<self.retry_after:return
        from configuration import Config
        from runtime import apply_config,write_status,runtime_dir
        from secure_bridge import call
        with control_lock(blocking=False) as acquired:
            if not acquired:return
            upgrade=runtime_dir()/'worker-upgrading'
            if upgrade.exists():
                with (runtime_dir()/'worker-upgrade.lock').open('a') as lock:
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:return
                    upgrade.unlink(missing_ok=True) # crashed starter, no active upgrade owner
            config=Config()
            try:state=call('service_status',timeout=2)
            except ValueError:
                # Recover a stale marker after a monitor restart only if systemd
                # proves the fixed protected service has already stopped.
                flag=runtime_dir()/'workspace-closing'
                if flag.exists():
                    import os,subprocess
                    try:
                        result=subprocess.run(['/usr/bin/systemctl','--no-ask-password','show','wallaby-agent-secure@'+str(os.getuid())+'.service','--property=ActiveState','--value'],capture_output=True,text=True,timeout=3)
                        if result.returncode==0 and result.stdout.strip() in ('inactive','failed'):
                            flag.unlink(missing_ok=True)
                            write_status('node','red','Off · protected service is stopped. Reconnect the node to start its workspace.',lifecycle=True)
                    except (OSError,subprocess.TimeoutExpired):pass
                return # Unavailable status is not evidence of a closed window.
            if not isinstance(state,dict) or not state.get('protected',{}).get('running'):return
            if state.get('status_pending'):return # A busy status refresh is not evidence of private unfinished work.
            if state.get('viewer_open'):self.legacy_view_seen=True;self.cleanup_wait_until=0
            recovery=state.get('recovery',{});expired=recovery.get('expired') is True
            notice=recovery.get('message') if expired else None
            closed=expired or (state.get('window_required') is True or 'window_required' not in state and self.legacy_view_seen) and state.get('viewer_open') is False
            if config.values['enabled']['node']:
                if not closed:return
                import copy
                new=copy.deepcopy(config.values);new['enabled']['node']=False
                apply_config(config,new)
            if state.get('busy'):
                write_status('node','red',(notice+'. ' if notice else '')+'Node interface is off. Protected RAM was retained for unfinished wallet work. Re-enable the node to resume it.',lifecycle=True,recovery_notice=notice)
                return
            flag=runtime_dir()/'workspace-closing';flag.write_text('closing\n')
            write_status('node','amber','Node disconnected. Closing its protected workspace and clearing RAM…',lifecycle=True,recovery_notice=notice)
            self.thread=threading.Thread(target=self.clean,args=(notice,),daemon=True);self.thread.start()
    def clean(self,notice=None):
        from secure_bridge import stop,call
        from runtime import write_status,runtime_dir
        try:
            stop()
            self.legacy_view_seen=False;self.cleanup_wait_until=0
            write_status('node','red',(notice+'. Automatic reconnection failed after 15 seconds. Turn on the node interface to retry.' if notice else 'Off · protected window closed and workspace cleared.'),lifecycle=True,recovery_notice=notice)
        except Exception as error:
            from activity_log import event
            from secure_bridge import WorkspaceFailure
            code=error.code if isinstance(error,WorkspaceFailure) else 'cleanup_unconfirmed'
            if code in ('workspace_status_pending','workspace_busy','worker_unreachable'):
                if not self.cleanup_wait_until:self.cleanup_wait_until=time.monotonic()+15
                if time.monotonic()<self.cleanup_wait_until:
                    self.retry_after=time.monotonic()+1
                    event('workspace.cleanup','Safe cleanup deferred · '+code+' · automatic guarded retry; RAM retained')
                    write_status('node','amber','Protected window closed. Waiting for the current local action to finish; safe cleanup will retry automatically.',lifecycle=True,recovery_notice=notice)
                    return
            event('workspace.cleanup','Cleanup did not confirm completion · '+code+' · '+type(error).__name__)
            self.retry_after=time.monotonic()+30
            write_status('node','red',(notice+'. ' if notice else '')+'Node interface is off, but protected workspace cleanup did not confirm completion. Keep the computer awake; re-enable the node to inspect unfinished work.',lifecycle=True,cleanup_failed=True,recovery_notice=notice)
        finally:(runtime_dir()/'workspace-closing').unlink(missing_ok=True)
