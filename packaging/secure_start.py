#!/usr/bin/python3 -I
"""Fixed authorised system-service and terminal recovery entry point. No RPC names, user paths or commands accepted."""
import os,pwd,subprocess,sys
from pathlib import Path

def runtime_parent(path):
    """Set root-owned traversal permissions despite inherited UMask=0077.

    The mounted RAM directory itself stays private (0700) to its user.
    """
    path.mkdir(mode=0o755,exist_ok=True)
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if info.st_uid!=0 or info.st_mode&0o022:raise SystemExit('Unsafe runtime parent.')
        os.fchmod(fd,0o755)
    finally:os.close(fd)

def wallet_paths(uid,home,unit_root=Path('/run/systemd/system'),service='renames'):
    """Root-owned, per-user exceptions for supported wallet roots only.

    Keep ProtectHome=read-only. An explicit nested wallet path overrides that
    mount instead of trying to make the parent /home directory writable.
    """
    if service not in ('renames','retirement','chain'):raise SystemExit('Unsupported wallet helper.')
    home=Path(home)
    if not home.is_absolute() or any(ord(c)<32 or ord(c)==127 for c in str(home)):raise SystemExit('Invalid account home directory.')
    runtime_parent(unit_root)
    folder=unit_root/('wallaby-agent-'+service+'@'+str(uid)+'.service.d');runtime_parent(folder)
    file=folder/'30-wallet-paths.conf'
    if file.is_symlink() or file.exists() and (file.stat().st_uid!=0 or file.stat().st_nlink!=1):raise SystemExit('Unsafe rename service configuration.')
    lines=['[Service]']
    if service in ('renames','chain'):lines.append('ReadWritePaths=') # Retirement also serves locally selected encrypted exports.
    for base in (home/'.bitcoin',home/'snap/bitcoin-core/common/.bitcoin'):
        for network in ('','testnet3','testnet4','signet','regtest'):
            value='-'+str(base/network if service=='chain' else base/network/'wallets')
            value=value.replace('%','%%').replace('\\','\\\\').replace('"','\\"')
            lines.append('ReadWritePaths="'+value+'"')
    fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o644)
    try:
        os.write(fd,('\n'.join(lines)+'\n').encode());os.fchmod(fd,0o644);os.fsync(fd)
    finally:os.close(fd)

def rename_paths(uid,home,unit_root=Path('/run/systemd/system')):
    wallet_paths(uid,home,unit_root,'renames')

def retirement_paths(uid,home,unit_root=Path('/run/systemd/system')):
    wallet_paths(uid,home,unit_root,'retirement')

def authorised_caller(uid):
    caller=os.environ.get('PKEXEC_UID')
    if caller is not None:return caller==str(uid)
    # A root-owned system unit starts this helper after systemd/Polkit has
    # authorised the administrator request. User-service cgroups cannot pass
    # main's root check, even with a matching unit basename.
    try:
        group=next(line.split('::',1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        return group.startswith('/system.slice/') and Path(group).name=='wallaby-agent-prepare@'+str(uid)+'.service'
    except (OSError,StopIteration):return False

def main():
    if os.geteuid()!=0 or len(sys.argv)!=2 or not sys.argv[1].isdecimal():raise SystemExit('Local administrator authorisation required.')
    uid=int(sys.argv[1])
    if uid<1000 or not authorised_caller(uid):raise SystemExit('Only the requesting desktop user may start its protected workspace.')
    account=pwd.getpwuid(uid);base=Path('/run/wallaby-agent-secure');runtime_parent(base)
    home=base/str(uid);runtime_parent(home)
    ram=home/'ram';ram.mkdir(mode=0o700,exist_ok=True)
    if ram.is_symlink():raise SystemExit('Unsafe RAM mount point.')
    if not os.path.ismount(ram):
        subprocess.run(['/usr/bin/mount','-t','tmpfs','-o','noswap,nodev,nosuid,noexec,size=2G,mode=0700,uid='+str(uid)+',gid='+str(account.pw_gid),'wallaby-agent-volatile',str(ram)],check=True)
    # Ownership must be set by the mount, not by trusting a user's marker.
    info=subprocess.run(['/usr/bin/findmnt','-n','-o','FSTYPE,OPTIONS','--target',str(ram)],capture_output=True,text=True,check=True).stdout
    if not info.startswith('tmpfs ') or 'noswap' not in info or ram.stat().st_uid!=uid:raise SystemExit('Non-swapping RAM storage could not be established.')
    escaped=subprocess.run(['/usr/bin/systemd-escape','--path','--suffix=mount',str(ram)],capture_output=True,text=True,check=True).stdout.strip()
    if '/' in escaped or not escaped.endswith('.mount'):raise SystemExit('Invalid generated mount unit.')
    unit=Path('/etc/systemd/system')/escaped
    text='[Unit]\nDescription=Wallaby non-swapping RAM for user '+str(uid)+'\n\n[Mount]\nWhat=wallaby-agent-volatile\nWhere='+str(ram)+'\nType=tmpfs\nOptions=noswap,nodev,nosuid,noexec,size=2G,mode=0700,uid='+str(uid)+',gid='+str(account.pw_gid)+'\nDirectoryMode=0755\n'
    if unit.is_symlink():raise SystemExit('Unsafe existing mount unit.')
    unit.write_text(text);unit.chmod(0o644)
    rename_paths(uid,account.pw_dir)
    retirement_paths(uid,account.pw_dir)
    wallet_paths(uid,account.pw_dir,service='chain')
    subprocess.run(['/usr/bin/systemctl','daemon-reload'],check=True)
    subprocess.run(['/usr/bin/systemctl','start','wallaby-agent-snap-ram@'+str(uid)+'.service'],check=True)
    subprocess.run(['/usr/bin/systemctl','start','wallaby-agent-secure@'+str(uid)+'.service'],check=True)

if __name__=='__main__':main()
