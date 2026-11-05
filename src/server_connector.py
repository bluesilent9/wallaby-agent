"""Initial server SSH socket only: prefer IPv6, then try IPv4.

OpenSSH still authenticates the original hostname; local/peer transports do not
use this connector. DNS uses Ubuntu's resolver IPC, not a remote DNS shortcut.
"""
import array,ipaddress,json,os,socket,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from configuration import hostname
from diagnostics import ConnectionFailure
from ipv6_resolver import resolve as resolve_ipv6,SOCKET,LIMIT

def resolve_ipv4(name,port,timeout=3):
    name=hostname(name)
    if type(port) is not int or not 0<port<=65535:raise ValueError('Invalid server port.')
    request={'method':'io.systemd.Resolve.ResolveHostname','parameters':{'name':name,'family':socket.AF_INET,'flags':0}}
    deadline=time.monotonic()+timeout
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
        channel.settimeout(timeout);channel.connect(SOCKET);channel.sendall(json.dumps(request,separators=(',',':')).encode()+b'\0');data=bytearray()
        while b'\0' not in data:
            channel.settimeout(max(.001,deadline-time.monotonic()));chunk=channel.recv(min(8192,LIMIT+1-len(data)))
            if not chunk:raise ValueError('Incomplete local resolver reply.')
            data.extend(chunk)
            if len(data)>LIMIT:raise ValueError('Local resolver reply exceeds limit.')
    reply=json.loads(bytes(data).split(b'\0',1)[0]);rows=reply.get('parameters',{}).get('addresses',[])
    if reply.get('error') or not isinstance(rows,list) or len(rows)>1024:raise ValueError('No usable IPv4 server address.')
    result=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('family')!=socket.AF_INET:continue
        raw=row.get('address')
        if not isinstance(raw,list) or len(raw)!=4 or any(type(b) is not int or not 0<=b<=255 for b in raw):raise ValueError('Invalid IPv4 resolver address.')
        address=ipaddress.IPv4Address(bytes(raw))
        if address.is_unspecified or address.is_multicast or int(address)==2**32-1:continue
        item=(str(address),port)
        if item not in result:result.append(item)
    if not result:raise ValueError('No usable IPv4 server address.')
    return result

def connect(name,port,timeout=10):
    deadline=time.monotonic()+timeout
    # Reserve half the attempt for fallback even when an IPv6 route blackholes.
    for family,resolver,budget in ((socket.AF_INET6,resolve_ipv6,timeout/2),(socket.AF_INET,resolve_ipv4,timeout)):
        end=min(deadline,time.monotonic()+budget)
        try:addresses=resolver(name,port,timeout=max(.001,min(3,end-time.monotonic())))
        except (ConnectionFailure,OSError,ValueError):continue
        for address in addresses:
            remaining=end-time.monotonic()
            if remaining<=0:break
            connection=None
            try:
                connection=socket.socket(family,socket.SOCK_STREAM)
                if family==socket.AF_INET6:connection.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
                connection.settimeout(min(remaining,2.5));connection.connect(address);connection.settimeout(None)
                return connection
            except OSError:
                if connection is not None:connection.close()
    raise ConnectionFailure('ssh','server_unreachable','Could not connect to the server over IPv6 or IPv4. Check its hostname, SSH port and network connection.')

def main():
    try:
        if len(sys.argv)!=3:raise ValueError('Invalid server socket handoff arguments.')
        with connect(sys.argv[1],int(sys.argv[2])) as connection:
            family='IPv6' if connection.family==socket.AF_INET6 else 'IPv4'
            print('WALLABY_SERVER '+family+': server socket connected; SSH authentication still required.',file=sys.stderr)
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM,fileno=os.dup(sys.stdout.fileno())) as channel:
                if channel.sendmsg([b'\0'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[connection.fileno()]))])!=1:raise OSError('Socket handoff failed.')
    except (ConnectionFailure,OSError,ValueError):
        print('WALLABY_CONNECT server_unreachable: Could not connect to the server over IPv6 or IPv4.',file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
