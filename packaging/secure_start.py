#!/usr/bin/python3 -I
"""Fixed local pkexec entry point. No RPC names, user paths or commands accepted."""
import os,pwd,subprocess,sys
from pathlib import Path

def main():
    if os.geteuid()!=0 or len(sys.argv)!=2 or not sys.argv[1].isdecimal():raise SystemExit('Local administrator authorisation required.')
    uid=int(sys.argv[1]);caller=os.environ.get('PKEXEC_UID')
    if uid<1000 or caller is None or caller!=str(uid):raise SystemExit('Only the requesting desktop user may start its protected workspace.')
    account=pwd.getpwuid(uid);base=Path('/run/wallaby-agent-secure');base.mkdir(mode=0o755,exist_ok=True)
    if base.is_symlink() or base.stat().st_uid!=0:raise SystemExit('Unsafe runtime parent.')
    home=base/str(uid);home.mkdir(mode=0o755,exist_ok=True)
    if home.is_symlink() or home.stat().st_uid!=0:raise SystemExit('Unsafe workspace parent.')
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
    subprocess.run(['/usr/bin/systemctl','daemon-reload'],check=True)
    subprocess.run(['/usr/bin/systemctl','start','wallaby-agent-snap-ram@'+str(uid)+'.service'],check=True)
    subprocess.run(['/usr/bin/systemctl','start','wallaby-agent-secure@'+str(uid)+'.service'],check=True)

if __name__=='__main__':main()
