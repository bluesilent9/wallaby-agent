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
Version: 2.0.0~dev4
Section: utils
Priority: optional
Architecture: {arch}
Maintainer: Wallaby Suite <347047153+bluesilent9@users.noreply.github.com>
Depends: python3 (>= 3.11), openssh-client, iputils-ping, systemd, xdg-utils
Recommends: kdialog | zenity
Description: Wallaby Agent V2 Development
 Per-user IPv6 DDNS-GO and Dashboard access, plus Bitcoin Core RPC transport.
 All tunnels are off on first install. Includes an HTML5 configuration page.
''')
for folder in ('src','web'):
 shutil.copytree(root/folder,stage/'usr/lib/wallaby-agent'/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(stage/'usr/bin').mkdir(parents=True,exist_ok=True)
subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-fPIE','-pie','-Wl,-z,relro,-z,now','-o',str(stage/'usr/bin/wallaby-agent'),str(root/'packaging/launcher.c')],check=True)
for kind in ('ddns','dashboard','node','monitor','ui'):
 extra='NoNewPrivileges=yes\n' if kind!='ui' else ''
 put(f'usr/lib/systemd/user/wallaby-agent-{kind}.service',f'''[Unit]
Description=Wallaby Agent V2 — {kind}
StartLimitIntervalSec=0

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
put('usr/share/doc/wallaby-agent/README.md',(root/'README.md').read_text())
put('DEBIAN/postinst','''#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q || true; fi
exit 0
''',0o755)
out=root/'dist'/f'wallaby-agent_2.0.0~dev4_{arch}.deb';out.parent.mkdir(exist_ok=True)
subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(out)],check=True)
print(out)
