"""Pass SSH pipes into the protected worker without parsing wallet bytes outside it."""
import array,json,os,socket,socketserver,stat,struct,sys,threading
from protected_memory import root


def handoff():
    source=os.environ.get('SSH_CONNECTION','')
    if not source or len(source)>512:raise ValueError('An SSH peer session is required.')
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(1800);s.connect(str(root()/'peer-helper.sock'))
        fds=array.array('i',[sys.stdin.fileno(),sys.stdout.fileno()]);s.sendmsg([source.encode()],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,fds)])
        if s.recv(16)!=b'COMPLETE':raise ValueError('Protected peer relay stopped. Check both Agents before a fresh attempt.')

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        fds=[]
        try:
            if struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]!=os.getuid():return
            self.request.settimeout(1800);data,ancillary,flags,_=self.request.recvmsg(512,socket.CMSG_SPACE(8))
            for level,kind,raw in ancillary:
                if level!=socket.SOL_SOCKET or kind!=socket.SCM_RIGHTS:raise ValueError('Invalid pipe handoff.')
                got=array.array('i');got.frombytes(raw[:len(raw)//got.itemsize*got.itemsize]);fds.extend(got)
            if flags&(socket.MSG_TRUNC|socket.MSG_CTRUNC):raise ValueError('Truncated pipe handoff.')
            if len(fds)!=2 or any(not (stat.S_ISFIFO(os.fstat(fd).st_mode) or stat.S_ISSOCK(os.fstat(fd).st_mode)) for fd in fds):raise ValueError('Only SSH pipes or sockets may cross this boundary, never persistent-file handles.')
            from peer_wallet import peer_receive
            with os.fdopen(os.dup(fds[0]),'rb',buffering=0) as inp,os.fdopen(os.dup(fds[1]),'wb',buffering=0) as out:peer_receive(inp,out,data.decode())
            self.request.sendall(b'COMPLETE')
        except Exception:
            try:self.request.sendall(b'STOPPED')
            except OSError:pass
        finally:
            for fd in fds:os.close(fd)

class Server(socketserver.ThreadingUnixStreamServer):daemon_threads=True

def start():
    path=root()/'peer-helper.sock';path.unlink(missing_ok=True);server=Server(str(path),Handler);path.chmod(0o600);threading.Thread(target=server.serve_forever,daemon=True).start();return server
