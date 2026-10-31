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
    def __init__(self):self.thread=None;self.retry_after=0
    def poll(self):
        from protected_memory import required
        if not required() or self.thread and self.thread.is_alive() or time.monotonic()<self.retry_after:return
        from configuration import Config
        from runtime import apply_config,write_status,runtime_dir
        from secure_bridge import call
        with control_lock(blocking=False) as acquired:
            if not acquired:return
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
            closed=state.get('window_required') is True and state.get('viewer_open') is False
            if config.values['enabled']['node']:
                if not closed:return
                import copy
                new=copy.deepcopy(config.values);new['enabled']['node']=False
                apply_config(config,new)
            if state.get('busy'):
                write_status('node','red','Node interface is off. Protected RAM was retained for unfinished wallet work. Re-enable the node to resume it.',lifecycle=True)
                return
            flag=runtime_dir()/'workspace-closing';flag.write_text('closing\n')
            write_status('node','amber','Node disconnected. Closing its protected workspace and clearing RAM…',lifecycle=True)
            self.thread=threading.Thread(target=self.clean,daemon=True);self.thread.start()
    def clean(self):
        from secure_bridge import stop,call
        from runtime import write_status,runtime_dir
        try:
            if call('ui.prepare_close',time.monotonic()+4,timeout=6).get('ok') is not True:raise ValueError('Protected worker did not confirm closing.')
            stop()
            write_status('node','red','Off · protected window closed and workspace cleared.',lifecycle=True)
        except Exception:
            self.retry_after=time.monotonic()+30
            write_status('node','red','Node interface is off, but protected workspace cleanup did not confirm completion. Keep the computer awake; re-enable the node to inspect unfinished work.',lifecycle=True)
        finally:(runtime_dir()/'workspace-closing').unlink(missing_ok=True)
