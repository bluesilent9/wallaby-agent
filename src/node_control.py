"""Local node-controller ownership; obsolete cleanup cannot stop a newer session."""
import contextlib,fcntl,os,re,stat
from diagnostics import ConnectionFailure

def owner(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{32}',value) is not None

def current(w,generation,controller):
    return generation==w.node_generation and controller==w.node_controller

def audit(w,action,matched=True):
    from activity_log import event
    from node_diagnostics import schedule
    event('node.control','action='+action+' · current_owner='+str(matched).lower()+' · epoch='+str(getattr(w,'node_epoch',0)))
    schedule('controller_change',w)

def control(w,method,args):
    with w.node_control_lock:
        if method=='node.connection_lost':
            if len(args) not in (2,4) or args[0] not in ('rpc','dashboard','ssh','ssh_forward','ssh_local') or not isinstance(args[1],str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',args[1]):raise ValueError('Invalid connection failure category.')
            # Legacy unscoped cleanup cannot interrupt an explicitly owned node.
            valid=(w.node_controller is None if len(args)==2 else current(w,args[2],args[3]))
            if not valid:
                audit(w,'obsolete_failure_ignored',False);return {'ok':True,'ignored':'superseded'}
            audit(w,'transport_failed')
            w.connection_lost(ConnectionFailure(args[0],args[1],'Node transport interrupted.'))
            if w.node_stop:w.node_stop.set()
            return {'ok':True}
        if len(args) not in (1,2):raise ValueError('Invalid node controller request.')
        controller=args[1] if len(args)==2 else None
        if not current(w,args[0],controller):
            audit(w,'obsolete_'+method.replace('.','_')+'_ignored',False)
            if method=='node.stop':return {'ok':True,'ignored':'superseded'}
            return {'color':'red','message':'A newer local node controller owns this connection.','failed':True,'superseded':True}
        if method=='node.stop':
            audit(w,'stop')
            if w.node_stop:w.node_stop.set()
            return {'ok':True}
        return dict(w.node_status)

def start(w,args):
    if len(args) not in (1,2) or type(args[0]) is not int or not 1<=args[0]<=65535 or len(args)==2 and not owner(args[1]):raise ValueError('Invalid local node connection.')
    port=args[0];controller=args[1] if len(args)==2 else None
    with w.node_control_lock:
        if controller is None and w.node_controller is not None:raise ValueError('Update and restart the ordinary Agent services before attaching to this protected node.')
        if w.node and w.node.is_alive():
            if port!=w.node_port or w.node_stop.is_set():raise ValueError('Previous node session is still closing. Its protected workspace was retained.')
            # Reuse the authenticated worker session rather than register twice.
            changed=w.node_controller!=controller;w.node_controller=controller
            audit(w,'controller_takeover' if changed else 'reattach')
            return {'session':w.node_generation}
        result=w.start_node(port,controller);audit(w,'start');return result

@contextlib.contextmanager
def runtime_owner(root):
    """One ordinary node service per user; a duplicate exits without publishing."""
    fd=os.open(root/'node-worker.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        s=os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=0o600:raise ValueError('Unsafe local node service lock.')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:yield False;return
        yield True
    finally:os.close(fd)
