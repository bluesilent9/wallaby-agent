"""Reopen presentation only; never stop a worker or discard its RAM state."""
import os,signal,time
from pathlib import Path
from secure_bridge import call,WorkspaceFailure
from worker_upgrade import identity
VIEWER='/usr/lib/wallaby-agent/src/protected_viewer.py'

def tracked_viewers(worker):
    group=Path('/proc',str(worker['pid']),'cgroup').read_text()
    if not any(line.startswith('0::') and Path(line.split('::',1)[1]).name=='wallaby-agent-secure@'+str(os.getuid())+'.service' for line in group.splitlines()):raise ValueError('The worker is outside its protected service; presentation recovery was refused.')
    rows=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdecimal():continue
        try:
            uids=next(line.split()[1:] for line in (p/'status').read_text().splitlines() if line.startswith('Uid:'))
            if any(int(uid)!=os.getuid() for uid in uids) or (p/'cgroup').read_text()!=group:continue
            stat=(p/'stat').read_text();fields=stat[stat.rfind(')')+2:].split()
            if int(fields[1])!=worker['pid']:continue
            args=(p/'cmdline').read_bytes().split(b'\0');args=[a.decode() for a in args if a]
            if args!=['/usr/bin/python3','-I','-B',VIEWER]:continue
            before=identity(int(p.name));fd=os.pidfd_open(int(p.name))
            if identity(int(p.name))!=before:os.close(fd);continue
            rows.append((fd,before))
        except (OSError,ValueError,UnicodeError,StopIteration):continue
    return rows

def resume(page='authorise'):
    if page not in ('authorise','synchronisation','burn','message','peers'):raise ValueError('Invalid protected page.')
    worker={};status=call('service_status',timeout=10,peer=worker)
    # Replace only exact viewer children in this worker's cgroup. A stuck Qt
    # process can exist even though no usable window is visible on this desktop.
    rows=tracked_viewers(worker)
    if status.get('viewer_open') and not rows:raise ValueError('The existing protected viewer could not be identified safely. Its worker and RAM were retained.')
    try:
        actual={};call('service_status',timeout=10,peer=actual)
        if actual!=worker:raise ValueError('The protected worker changed; retry without restarting anything.')
        for fd,_ in rows:
            try:signal.pidfd_send_signal(fd,signal.SIGTERM)
            except ProcessLookupError:pass
        deadline=time.monotonic()+3
        while rows and time.monotonic()<deadline:
            if not any(alive(p) for _,p in rows):break
            time.sleep(.05)
        for fd,p in rows:
            if alive(p):
                try:signal.pidfd_send_signal(fd,signal.SIGKILL)
                except ProcessLookupError:pass
        deadline=time.monotonic()+2
        while any(alive(p) for _,p in rows) and time.monotonic()<deadline:time.sleep(.05)
        if any(alive(p) for _,p in rows):raise ValueError('The old presentation has not exited; its worker remains untouched.')
        call('ui.arm',timeout=10)
        result=call('ui.open',page,timeout=15)
        actual={};opened=call('service_status',timeout=10,peer=actual)
        if actual!=worker:raise ValueError('The worker changed while reopening presentation; inspect its current status.')
        if not opened.get('viewer_open'):raise ValueError('The protected viewer did not stay open. Its worker and RAM were retained; check the current desktop display and installed Qt components.')
        return {'message':result.get('message','Reopened the protected window.')+' The wallet worker and protected RAM were retained.'}
    finally:
        for fd,_ in rows:os.close(fd)

def alive(process):
    try:
        p=Path('/proc',str(process['pid']));s=(p/'stat').read_text();fields=s[s.rfind(')')+2:].split()
        return fields[0]!='Z' and identity(process['pid'])==process
    except OSError:return False
