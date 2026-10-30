#!/usr/bin/python3
"""Hold the inherited sleep inhibitor until all temporary children and RAM data are gone."""
import os,shutil,signal,socket,subprocess,sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from protected_memory import root,enforce


def ancestors():
    result=set();pid=os.getpid()
    for _ in range(32):
        if pid<=1:break
        result.add(pid)
        try:pid=int(Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[1])
        except (OSError,ValueError,IndexError):break
    return result

def cgroup():
    return next(line.split('::',1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))

def members(exempt):
    group=cgroup();pids=(Path('/sys/fs/cgroup')/group.lstrip('/')/'cgroup.procs').read_text().split();result=[]
    for value in pids:
        pid=int(value)
        if pid in exempt:continue
        try:
            if Path('/proc',value,'stat').read_text().rsplit(')',1)[1].split()[0]!='Z':result.append(pid)
        except OSError:pass
    return result

def send(pid,sig):
    # Pin the process before signalling so PID reuse cannot target production Core.
    try:fd=os.pidfd_open(pid)
    except ProcessLookupError:return
    try:
        if '0::'+cgroup() not in Path('/proc',str(pid),'cgroup').read_text().splitlines():raise RuntimeError('Temporary child changed protection group.')
        signal.pidfd_send_signal(fd,sig)
    except ProcessLookupError:pass
    finally:os.close(fd)

def cleanup(exempt,workspace):
    pending=members(exempt)
    for pid in pending:send(pid,signal.SIGTERM)
    for _ in range(240):
        pending=members(exempt)
        if not pending:break
        time.sleep(.25)
    else:
        # Only this fixed protected cgroup. Production Core/history services are
        # outside it and are never terminated by protected-workspace cleanup.
        for pid in pending:send(pid,signal.SIGKILL)
        for _ in range(40):
            if not members(exempt):break
            time.sleep(.1)
        if members(exempt):raise RuntimeError('Temporary child cleanup did not complete.')
    for path in Path(workspace).iterdir():
        if path.name=='supervisor.sock':continue
        if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
        else:path.unlink(missing_ok=True)


def main():
    enforce();workspace=root();path=workspace/'supervisor.sock';path.unlink(missing_ok=True)
    listener=socket.socket(socket.AF_UNIX);listener.bind(str(path));path.chmod(0o600);listener.listen(1);listener.settimeout(.5)
    process=subprocess.Popen(['/usr/bin/python3','-I','-B',str(Path(__file__).with_name('secure_worker.py'))],start_new_session=True)
    stopping=None;exempt=ancestors()
    try:
        while process.poll() is None:
            try:
                conn,_=listener.accept();data=conn.recv(16)
                import struct
                peer_pid,uid,_=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid==os.getuid() and data==b'STOP':stopping=conn;exempt.add(peer_pid);break
                conn.close()
            except socket.timeout:pass
        cleanup(exempt,workspace)
        if stopping:stopping.sendall(b'CLEAN');stopping.close()
        process.wait(timeout=10)
    except Exception:
        # Fail closed: keep the supervising inhibitor alive for local inspection.
        while True:time.sleep(30)
    finally:listener.close();path.unlink(missing_ok=True)

if __name__=='__main__':main()
