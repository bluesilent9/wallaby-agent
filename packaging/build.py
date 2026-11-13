#!/usr/bin/python3
"""Build an Ubuntu 26.04 DEB without root or network dependencies."""
import os,shutil,subprocess
from pathlib import Path
from release_check import release_version
root=Path(__file__).resolve().parent.parent
version,build_number=release_version(root)
stage=root/'build/package'
if stage.exists():shutil.rmtree(stage)
def put(path,text,mode=0o644):
 p=stage/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(mode)
arch=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
put('DEBIAN/control',f'''Package: wallaby-agent
Version: {version}
Section: utils
Priority: optional
Architecture: {arch}
Maintainer: Wallaby Suite <347047153+bluesilent9@users.noreply.github.com>
Depends: python3 (>= 3.11), openssh-client, systemd, xdg-utils, iproute2, python3-cryptography, python3-paramiko (>= 3.4), python3-zxing-cpp, python3-pil, util-linux
Suggests: systemd-resolved, pkexec, polkitd, python3-pyqt6, python3-pyqt6.qtwebengine, kdialog | zenity, xorriso, openssh-server, ufw
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
put('usr/lib/systemd/system/wallaby-agent-prepare@.service','''[Unit]
Description=Wallaby Agent administrator preparation for user %i
After=systemd-logind.service

[Service]
Type=oneshot
User=root
ExecStart=/usr/lib/wallaby-agent/secure-start %i
TimeoutStartSec=120
UMask=0077
NoNewPrivileges=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX AF_INET6 AF_NETLINK
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_DAC_OVERRIDE CAP_FOWNER
StandardOutput=journal
StandardError=journal
''')
put('usr/lib/systemd/system/wallaby-agent-secure@.service','''[Unit]
Description=Wallaby Agent protected Bitcoin workspace for user %i
After=systemd-logind.service
Requires=systemd-logind.service wallaby-agent-snap-ram@%i.service wallaby-agent-denials-v2@%i.service wallaby-agent-retirement@%i.service wallaby-agent-renames@%i.service
Wants=wallaby-agent-peers@%i.service wallaby-agent-chain@%i.service
After=wallaby-agent-snap-ram@%i.service wallaby-agent-denials-v2@%i.service wallaby-agent-retirement@%i.service wallaby-agent-renames@%i.service wallaby-agent-chain@%i.service wallaby-agent-peers@%i.service
RequiresMountsFor=/run/wallaby-agent-secure/%i/ram

[Service]
Type=exec
User=%i
SupplementaryGroups=cdrom video
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
OOMPolicy=continue
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
DeviceAllow=char-video4linux rw
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictNamespaces=~cgroup
RestrictRealtime=yes
RestrictAddressFamilies=AF_UNIX AF_INET6 AF_INET AF_NETLINK
LockPersonality=yes
CapabilityBoundingSet=
StandardOutput=null
StandardError=null
KillMode=control-group
TimeoutStopSec=90
Restart=no
''')
put('usr/lib/systemd/system/wallaby-agent-chain@.service','''[Unit]
Description=Wallaby Agent locally authorised cold blockchain clone for user %i
PartOf=wallaby-agent-secure@%i.service

[Service]
Type=exec
User=%i
ExecStart=/usr/bin/python3 -I -B /usr/lib/wallaby-agent/src/chain_clone_service.py
RuntimeDirectory=wallaby-agent-chain/%i
RuntimeDirectoryMode=0700
Environment=XDG_RUNTIME_DIR=/run/user/%i
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%i/bus
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
MemorySwapMax=0
MemoryZSwapMax=0
MemoryZSwapWriteback=no
LimitCORE=0
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX AF_INET6
CapabilityBoundingSet=
StandardOutput=journal
StandardError=journal
TimeoutStopSec=330
Restart=on-failure
RestartSec=5
''')
put('usr/lib/systemd/system/wallaby-agent-retirement@.service','''[Unit]
Description=Wallaby Agent local approved wallet removal and encrypted export for user %i
PartOf=wallaby-agent-secure@%i.service

[Service]
Type=exec
User=%i
ExecStart=/usr/bin/python3 -I -B /usr/lib/wallaby-agent/src/wallet_deletion.py
RuntimeDirectory=wallaby-agent-retirement/%i
RuntimeDirectoryMode=0700
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=-/home
PrivateTmp=yes
PrivateDevices=yes
MemorySwapMax=0
MemoryZSwapMax=0
MemoryZSwapWriteback=no
LimitCORE=0
Environment=LD_PRELOAD=/usr/lib/wallaby-agent/libno-dump.so
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=
StandardOutput=null
StandardError=null
Restart=on-failure
RestartSec=5
''')
put('usr/lib/systemd/system/wallaby-agent-renames@.service','''[Unit]
Description=Wallaby Agent locally approved atomic wallet rename for user %i
PartOf=wallaby-agent-secure@%i.service

[Service]
Type=exec
User=%i
ExecStart=/usr/bin/python3 -I -B /usr/lib/wallaby-agent/src/wallet_rename.py
RuntimeDirectory=wallaby-agent-renames/%i
RuntimeDirectoryMode=0700
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only

PrivateTmp=yes
PrivateDevices=yes
MemorySwapMax=0
MemoryZSwapMax=0
MemoryZSwapWriteback=no
LimitCORE=0
Environment=LD_PRELOAD=/usr/lib/wallaby-agent/libno-dump.so
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=
StandardOutput=null
StandardError=null
Restart=on-failure
RestartSec=5
''')
put('usr/lib/systemd/system/wallaby-agent-denials@.service','''[Unit]
Description=Wallaby Agent persistent denial preferences for user %i

[Service]
Type=exec
User=%i
ExecStart=/usr/bin/python3 -I -B /usr/lib/wallaby-agent/src/denial_storage.py --legacy-socket
StateDirectory=wallaby-agent-denials/%i
StateDirectoryMode=0700
RuntimeDirectory=wallaby-agent-denials/%i
RuntimeDirectoryMode=0700
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=
LimitCORE=0
StandardOutput=null
StandardError=null
Restart=on-failure
RestartSec=5
''')
put('usr/lib/systemd/system/wallaby-agent-denials-v2@.service','''[Unit]
Description=Wallaby Agent persistent archive and sync denial preferences for user %i

[Service]
Type=exec
User=%i
ExecStart=/usr/bin/python3 -I -B /usr/lib/wallaby-agent/src/denial_storage.py
StateDirectory=wallaby-agent-denials/%i
StateDirectoryMode=0700
RuntimeDirectory=wallaby-agent-denials-v2/%i
RuntimeDirectoryMode=0700
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=
LimitCORE=0
StandardOutput=null
StandardError=null
Restart=on-failure
RestartSec=5
''')
put('usr/lib/systemd/system/wallaby-agent-peers@.service','''[Unit]
Description=Wallaby Agent persistent peer communication trust for user %i
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=exec
User=%i
ExecStart=/usr/bin/python3 -I -B /usr/lib/wallaby-agent/src/peer_storage.py
StateDirectory=wallaby-agent-peers/%i
StateDirectoryMode=0700
RuntimeDirectory=wallaby-agent-peers/%i
RuntimeDirectoryMode=0700
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=
MemorySwapMax=0
MemoryZSwapMax=0
LimitCORE=0
StandardOutput=null
StandardError=journal
Restart=on-failure
RestartSec=5
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
 var manage=action.id === "org.freedesktop.systemd1.manage-units";
 var inhibit=action.id === "org.freedesktop.login1.inhibit-block-sleep" || action.id === "org.freedesktop.login1.inhibit-block-shutdown";
 if (!manage && !inhibit) return;
 if (manage && action.lookup("verb") !== "start" && action.lookup("verb") !== "stop") return;
 var uid;
 try { uid=polkit.spawn(["/usr/bin/id","-u","--",subject.user]).trim(); } catch(e) { return; }
 if (!/^[0-9]+$/.test(uid) || Number(uid)<1000) return;
 var ownUnit="wallaby-agent-secure@"+uid+".service";
 // system_unit is supplied by polkit from the root-owned system unit, not
 // from the caller's command line or from a user-creatable unit name.
 if (inhibit) {
  if (subject.system_unit === ownUnit && subject.no_new_privileges === true) return polkit.Result.YES;
  return;
 }
 if (action.lookup("unit") === ownUnit) return polkit.Result.YES;
});
''')
for kind in ('ddns','dashboard','node','monitor','ui'):
 extra='NoNewPrivileges=yes\n'
 families='AF_UNIX AF_INET6 AF_NETLINK'+(' AF_INET' if kind=='monitor' else '')
 dependencies='Requires=wallaby-agent-monitor.service\nPartOf=wallaby-agent-monitor.service\nAfter=wallaby-agent-monitor.service\n' if kind in ('ddns','dashboard','node') else ''
 put(f'usr/lib/systemd/user/wallaby-agent-{kind}.service',f'''[Unit]
Description=Wallaby Agent V2 — {kind}
{dependencies}StartLimitIntervalSec=0

[Service]
Type=simple
Environment=WALLABY_REQUIRE_PROTECTION=1
ExecStart=/usr/bin/wallaby-agent {kind}
Restart=on-failure
RestartSec=30
UMask=0077
KillMode=control-group
TimeoutStopSec=8
RestrictAddressFamilies={families}
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
for document in ('README.md','AGENT_BUILD86_HELPER_STARTUP.md','AGENT_BUILD85_SESSION_OWNERSHIP_AND_DIAGNOSTICS.md','AGENT_BUILD84_RECEIVER_INITIATED_SYNC.md','AGENT_BUILD83_RECOVERY_CLONE_HANDOVER.md','AGENT_BUILD82_TRUSTED_CHAIN_CLONE.md','AGENT_BUILD81_EXTINCTION_CONTINUATION.md','AGENT_BUILD80_CORE_RESTART.md','AGENT_BUILD78_EXTINCT_SYNC_PROTOCOL.md','AGENT_BUILD77_WHOLE_EXTINCT_UPGRADE.md','AGENT_BUILD76_PEER_STARTUP.md','AGENT_BUILD75_SCAN_CONNECT.md','AGENT_BUILD74_CAMERA_PAIRING.md','AGENT_BUILD73_SYNC_VISIBILITY.md','AGENT_BUILD72_RECEIVER_PERMISSIONS.md','AGENT_BUILD71_UNIFIED_SYNC.md','AGENT_BUILD70_SYNC_OFFERS.md','AGENT_BUILD69_BLOCK_DOWNLOAD.md','AGENT_BUILD68_STARTUP_RECOVERY.md','AGENT_BUILD67_DIRECT_PEERS.md','AGENT_BUILD66_ENCRYPTED_PEERS.md','NOISE_LICENSE','QR_CODE_LICENSE.md','AGENT_BUILD65_ORIGINAL_SIGNER_RESTORATION.md','AGENT_BUILD64_HISTORY_AND_SSH.md','AGENT_BUILD63_CORE_RESTART.md','AGENT_BUILD62_EXTINCTION_HISTORY.md','AGENT_BUILD61_EXTINCTION_CONFIRMATION.md','BUILD60_ADDRESS_COMPARISON.md','AGENT_BUILD59_RESPONSIVE_REVIEW.md','AGENT_BUILD58_GROUPED_REFRESH.md','AGENT_BUILD57_REFRESH_RECOVERY.md','AGENT_BUILD56_AUTOMATIC_BROADCAST.md','AGENT_BUILD55_DELIVERY_SERVER.md','AGENT_BUILD54_TRANSACTION_REVIEW.md','AGENT_BUILD53_STARTUP_AUTHORISATION.md','AGENT_BUILD52_OPTICAL_READBACK.md','AGENT_BUILD51_ETA_SELECTION.md','AGENT_BUILD50_ARCHIVE_DRIVES.md','AGENT_BUILD49_DISC_READBACK.md','AGENT_BUILD48_WRITER_PROGRESS.md','AGENT_BUILD47_DISC_OPERATIONS.md','DASHBOARD_BUILD47_DISC_REPEATS.md','AGENT_BUILD46_PASSPHRASES.md','AGENT_BUILD45_PRUNED_INSTALLATION.md','AGENT_BUILD44_RESPONSIVENESS.md','AGENT_BUILD43_DNS.md','AGENT_BUILD42_IPV6.md','AGENT_BUILD28_SYNC.md','AGENT_BUILD29_SYNC.md','AGENT_BUILD30_EXTINCTION.md','DASHBOARD_ARCHIVE_RESULTS_BUILD30.md','AGENT_BUILD31_CANCELLATION.md','AGENT_BUILD32_RENAME.md','AGENT_BUILD33_CARDS.md','AGENT_BUILD34_REVIEWS.md','AGENT_BUILD35_CANCELLATION.md','AGENT_BUILD36_DIALOGUES.md','AGENT_BUILD37_ROLE_NAMES.md','AGENT_BUILD38_CLEANUP.md','AGENT_BUILD39_ARCHIVE_AVAILABILITY.md','AGENT_BUILD40_MANAGED_ACCOUNTS.md','AGENT_BUILD41_COMBINED_WALLETS.md','AGENT_BUILD27_LIFECYCLE.md','AGENT_BUILD26_SYNC.md','AGENT_PROTOCOL.md','APPROVAL_PROTOCOL.md','DASHBOARD_PREVIEW_UPDATE.md','DASHBOARD_BUILD8_UPDATE.md','DASHBOARD_BUILD9_UPDATE.md','DASHBOARD_BUILD10_UPDATE.md','DASHBOARD_BUILD11_UPDATE.md','DASHBOARD_BUILD12_UPDATE.md','DASHBOARD_BUILD14_DIAGNOSTICS.md','AGENT_BUILD15_STARTUP.md','AGENT_BUILD16_STARTUP.md','AGENT_BUILD17_LIFECYCLE.md','AGENT_BUILD18_LIFECYCLE.md','AGENT_BUILD19_LOGS.md','AGENT_BUILD20_CLOSE.md','AGENT_BUILD21_NATIVE_CLOSE.md','AGENT_BUILD22_RECOVERY.md','DASHBOARD_BUILD27_ARCHIVES.md','DASHBOARD_BUILD28_SYNC.md','DASHBOARD_RENAME_PROTOCOL.md','DASHBOARD_FEE_PAGING.md','DASHBOARD_BUILD20_CANCELLATION.md','DASHBOARD_BUILD18_RETIREMENT.md','DISC_FORMAT.md','VALIDATION.md'):
 put('usr/share/doc/wallaby-agent/'+document,(root/document).read_text())
put('usr/lib/wallaby-agent/configure-renames',(root/'packaging/configure_renames.py').read_text(),0o755)
put('DEBIAN/postinst','''#!/bin/sh
set -e
/usr/bin/python3 -I -B /usr/lib/wallaby-agent/configure-renames
systemctl daemon-reload || true
if [ -d /sys/kernel/security/apparmor ] && command -v apparmor_parser >/dev/null 2>&1; then apparmor_parser -r /etc/apparmor.d/wallaby-agent-protected; fi
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q || true; fi
exit 0
''',0o755)
out=root/'dist'/f'wallaby-agent_{version}_{arch}.deb';out.parent.mkdir(exist_ok=True)
# Source checkout modes must not become installed group-writable code.
stage.chmod(0o755)
for path in stage.rglob('*'):
 if path.is_symlink():raise ValueError('Unexpected package symlink.')
 path.chmod(0o755 if path.is_dir() or path.stat().st_mode&0o111 else 0o644)
subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(out)],check=True)
print(out)
