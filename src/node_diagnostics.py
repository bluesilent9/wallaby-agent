"""Allowlisted local process/service evidence; no arguments, tokens or wallet data."""
import os,re,stat,subprocess,threading,time,sys
from pathlib import Path
_lock=threading.Lock();_last={};_running=False
NUMBERS={'MainPID','ExecMainStatus','NRestarts','MemoryCurrent','MemoryPeak','MemoryMax'}
STATES={'ActiveState','SubState','Result'}

def service(user):
    unit='wallaby-agent-node.service' if user else 'wallaby-agent-secure@'+str(os.getuid())+'.service'
    keys=sorted(NUMBERS|STATES|{'ExecStart','FragmentPath','DropInPaths','ControlGroup'})
    args=['/usr/bin/systemctl']+(['--user'] if user else [])+['show',unit,'--no-pager']+['-p'+k for k in keys]
    try:
        result=subprocess.run(args,capture_output=True,text=True,timeout=.8)
        if result.returncode:return {'available':False,'exit_code':result.returncode}
        raw=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line);out={'available':True}
        for k in NUMBERS:
            value=raw.get(k,'')
            if value.isdecimal() and len(value)<=20:out[k]=int(value)
        for k in STATES:
            if re.fullmatch('[a-z-]{1,24}',raw.get(k,'')):out[k]=raw[k]
        out['packaged_unit']=raw.get('FragmentPath')==('/usr/lib/systemd/user/'+unit if user else '/usr/lib/systemd/system/wallaby-agent-secure@.service')
        out['dropins']=len(raw.get('DropInPaths','').split())
        if user:out['packaged_launcher']=bool(re.search(r'path=/usr/bin/wallaby-agent(?:[ ;])',raw.get('ExecStart','')))
        group=raw.get('ControlGroup','')
        if not user and group.startswith('/') and len(group)<512:
            base=Path('/sys/fs/cgroup');path=(base/group.lstrip('/')/'memory.events').resolve()
            if path.is_relative_to(base):
                try:
                    events=dict(line.split() for line in path.read_text()[:4096].splitlines())
                    out['memory_events']={k:int(events[k]) for k in ('oom','oom_kill','max','high') if events.get(k,'').isdecimal()}
                except (OSError,ValueError):pass
        return out
    except (OSError,subprocess.TimeoutExpired,ValueError):return {'available':False}

def snapshot(reason,workspace=None):
    """Bounded independent checks. Diagnostic failures never change node state."""
    try:
        if not re.fullmatch('[a-z_]{1,32}',reason):return
        from activity_log import event
        from protected_memory import required,inside
        from worker_upgrade import VERSION,PROTOCOL
        import json
        info={'reason':reason,'pid':os.getpid(),'ppid':os.getppid(),'loaded_build':VERSION,'protocol':PROTOCOL,'protection_required':required(),'inside_protection':inside()}
        for module in ('app','runtime','node_client'):
            value=getattr(sys.modules.get(module),'PROCESS_BUILD',None)
            if isinstance(value,str) and re.fullmatch(r'2\.0\.0~dev[1-9][0-9]*',value):info[module+'_build']=value
        try:
            for line in Path('/proc/self/status').read_text().splitlines():
                key,_,value=line.partition(':')
                if key in ('VmRSS','VmPeak','Threads','NoNewPrivs','Seccomp'):
                    match=re.fullmatch(r'\s*([0-9]+)(?: kB)?\s*',value)
                    if match:info[key]=int(match[1])
        except OSError:pass
        if workspace is not None:
            info.update(epoch=workspace.node_epoch,controller_present=workspace.node_controller is not None,node_thread_alive=bool(workspace.node and workspace.node.is_alive()),node_stop_set=bool(workspace.node_stop and workspace.node_stop.is_set()),connected=workspace.node_status.get('color')=='green',viewers=sum(p.poll() is None for p in workspace.viewers))
        event('node.diagnostics',json.dumps(info,sort_keys=True))
        for user in (True,False):event('node.service',json.dumps({'kind':'ordinary' if user else 'protected',**service(user)},sort_keys=True))
    except Exception:pass

def schedule(reason,workspace=None):
    global _running
    with _lock:
        now=time.monotonic()
        if _running or now-_last.get(reason,-1000)<10:return
        _running=True;_last[reason]=now
    def work():
        global _running
        try:snapshot(reason,workspace)
        finally:
            with _lock:_running=False
    threading.Thread(target=work,daemon=True,name='bounded-node-diagnostics').start()

def export_text():
    from activity_log import DiagnosticLog,event
    from protected_memory import inside
    snapshot('log_export')
    if not inside():
        try:
            from secure_bridge import call
            rows=call('diagnostics.export',timeout=5)
            if not isinstance(rows,list) or len(rows)>20000 or any(not isinstance(r,dict) or r.get('origin')!='protected' for r in rows):raise ValueError('Invalid protected diagnostics.')
            DiagnosticLog().merge(rows);event('diagnostics.handoff','Current protected diagnostics included in log export.')
        except (ValueError,OSError):event('diagnostics.handoff','Protected diagnostics unavailable at export. Ordinary process and service snapshot included; no workspace or wallet operation was changed.')
    return DiagnosticLog().text()
