#!/usr/bin/python3
"""Build an Ubuntu 26.04 DEB without root or network dependencies."""
import os,shutil,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent.parent
stage=root/'build/package'
if stage.exists():shutil.rmtree(stage)
def put(path,text,mode=0o644):
 p=stage/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(mode)
arch=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
put('DEBIAN/control',f'''Package: wallaby-agent
Version: 2.0.0~dev10
Section: utils
Priority: optional
Architecture: {arch}
Maintainer: Wallaby Suite <347047153+bluesilent9@users.noreply.github.com>
Depends: python3 (>= 3.11), openssh-client, systemd, xdg-utils, iproute2, python3-cryptography, policykit-1, xorriso, util-linux, python3-pyqt6.qtwebengine, python3-pyqt6
Recommends: kdialog | zenity, bitcoind
Suggests: openssh-server, ufw, policykit-1
Description: Wallaby Agent V2 Development
 Per-user IPv6 tunnels, read-only node RPC and local wallet authorisation.
 All tunnels are off on first install. Includes an HTML5 configuration page.
''')
for folder in ('src','web'):
 shutil.copytree(root/folder,stage/'usr/lib/wallaby-agent'/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(stage/'usr/bin').mkdir(parents=True,exist_ok=True)
subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-fPIE','-pie','-Wl,-z,relro,-z,now','-o',str(stage/'usr/bin/wallaby-agent'),str(root/'packaging/launcher.c')],check=True)
shutil.copyfile(root/'packaging/secure_start.py',stage/'usr/lib/wallaby-agent/secure-start')
(stage/'usr/lib/wallaby-agent/secure-start').chmod(0o755)
shutil.copyfile(root/'packaging/secure_snap_ram.py',stage/'usr/lib/wallaby-agent/secure-snap-ram')
(stage/'usr/lib/wallaby-agent/secure-snap-ram').chmod(0o755)
subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared','-Wl,-z,relro,-z,now','-o',str(stage/'usr/lib/wallaby-agent/libno-dump.so'),str(root/'packaging/no_dump.c')],check=True)
put('usr/lib/systemd/system/wallaby-agent-secure@.service','''[Unit]
Description=Wallaby Agent protected Bitcoin workspace for user %i
After=systemd-logind.service
Requires=systemd-logind.service wallaby-agent-snap-ram@%i.service
After=wallaby-agent-snap-ram@%i.service
RequiresMountsFor=/run/wallaby-agent-secure/%i/ram

[Service]
Type=exec
User=%i
SupplementaryGroups=cdrom
ExecStart=/usr/bin/systemd-inhibit --what=sleep:shutdown --mode=block --who=WallabyAgent --why=Protected-Bitcoin-material-in-RAM /usr/bin/python3 -I -B /usr/lib/wallaby-agent/src/secure_supervisor.py
ExecStop=/usr/bin/python3 -B /usr/lib/wallaby-agent/src/secure_stop.py
Environment=WALLABY_REQUIRE_PROTECTION=1 WALLABY_PROTECTED_WORKER=1 PYTHONDONTWRITEBYTECODE=1
Environment=XDG_RUNTIME_DIR=/run/user/%i
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%i/bus
Environment=LD_PRELOAD=/usr/lib/wallaby-agent/libno-dump.so
UMask=0077
MemoryAccounting=yes
MemorySwapMax=0
MemoryZSwapMax=0
MemoryZSwapWriteback=no
MemoryMax=3G
LimitCORE=0
CoredumpFilter=0x0
NoNewPrivileges=yes
AppArmorProfile=wallaby-agent-protected
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/run/wallaby-agent-secure/%i/ram
TemporaryFileSystem=/tmp:rw,noswap,mode=1777 /var/tmp:rw,noswap,mode=1777 /dev/shm:rw,noswap,mode=1777
PrivateMounts=yes
PrivateIPC=yes
DevicePolicy=closed
DeviceAllow=block-sr rw
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictNamespaces=~cgroup
RestrictRealtime=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
LockPersonality=yes
CapabilityBoundingSet=
StandardOutput=null
StandardError=null
KillMode=control-group
TimeoutStopSec=90
Restart=no
''')
put('usr/lib/systemd/system/wallaby-agent-snap-ram@.service','''[Unit]
Description=Expose protected RAM to Bitcoin Core Snap for user %i
RequiresMountsFor=/run/wallaby-agent-secure/%i/ram
Before=wallaby-agent-secure@%i.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I -B /usr/lib/wallaby-agent/secure-snap-ram %i
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_DAC_OVERRIDE CAP_FOWNER
StandardOutput=null
StandardError=null
''')
put('etc/apparmor.d/wallaby-agent-protected','''abi <abi/4.0>,
include <tunables/global>
# Selected explicitly by the fixed system service, never a global userns switch.
# systemd supplies the no-swap, read-only filesystem and optical-device limits.
profile wallaby-agent-protected flags=(unconfined) {
  userns,
  /usr/bin/systemd-inhibit rix,
  /usr/bin/python3{,.*} rix,
  /usr/lib/**/QtWebEngineProcess rix,
}
''')
put('usr/share/polkit-1/rules.d/49-wallaby-agent-workspace.rules','''// Only the caller's own fixed, unprivileged Bitcoin worker. No arbitrary units.
polkit.addRule(function(action, subject) {
 if (action.id !== "org.freedesktop.systemd1.manage-units") return;
 var verb=action.lookup("verb");
 if (verb !== "start" && verb !== "stop") return;
 var uid;
 try { uid=polkit.spawn(["/usr/bin/id","-u",subject.user]).trim(); } catch(e) { return; }
 if (!/^[0-9]+$/.test(uid) || Number(uid)<1000) return;
 if (action.lookup("unit") === "wallaby-agent-secure@"+uid+".service") return polkit.Result.YES;
});
''')
for kind in ('ddns','dashboard','node','monitor','ui'):
 extra='NoNewPrivileges=yes\n' if kind!='ui' else ''
 dependencies='Requires=wallaby-agent-monitor.service\nPartOf=wallaby-agent-monitor.service\nAfter=wallaby-agent-monitor.service\n' if kind in ('ddns','dashboard','node') else ''
 put(f'usr/lib/systemd/user/wallaby-agent-{kind}.service',f'''[Unit]
Description=Wallaby Agent V2 — {kind}
{dependencies}StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=/usr/bin/wallaby-agent {kind}
Restart=on-failure
RestartSec=30
UMask=0077
KillMode=control-group
TimeoutStopSec=8
{extra}
[Install]
WantedBy=default.target
''')
put('usr/share/applications/wallaby-agent.desktop','''[Desktop Entry]
Type=Application
Name=Wallaby Agent Configuration
Comment=Configure your secure connections and Bitcoin Core node
Exec=wallaby-agent configure
Icon=wallaby-agent
Terminal=false
Categories=Utility;Settings;
StartupNotify=false
''')
put('etc/xdg/autostart/wallaby-agent-bootstrap.desktop','''[Desktop Entry]
Type=Application
Name=Wallaby Agent startup
Comment=Start the per-user server connectivity monitor
Exec=wallaby-agent bootstrap
Terminal=false
NoDisplay=true
X-KDE-autostart-phase=2
''')
put('usr/share/icons/hicolor/scalable/apps/wallaby-agent.svg',(root/'web/wallaby-agent.svg').read_text())
for document in ('README.md','AGENT_PROTOCOL.md','APPROVAL_PROTOCOL.md','DASHBOARD_PREVIEW_UPDATE.md','DASHBOARD_BUILD8_UPDATE.md','DASHBOARD_BUILD9_UPDATE.md','DASHBOARD_BUILD10_UPDATE.md','DISC_FORMAT.md','VALIDATION.md'):
 put('usr/share/doc/wallaby-agent/'+document,(root/document).read_text())
put('DEBIAN/postinst','''#!/bin/sh
set -e
systemctl daemon-reload || true
if [ -d /sys/kernel/security/apparmor ] && command -v apparmor_parser >/dev/null 2>&1; then apparmor_parser -r /etc/apparmor.d/wallaby-agent-protected; fi
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q || true; fi
exit 0
''',0o755)
out=root/'dist'/f'wallaby-agent_2.0.0~dev10_{arch}.deb';out.parent.mkdir(exist_ok=True)
subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(out)],check=True)
print(out)
