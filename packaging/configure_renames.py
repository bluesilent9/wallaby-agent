#!/usr/bin/python3 -I
"""Installer-only metadata refresh for already prepared user workspaces."""
import os,pwd,runpy
from pathlib import Path

def configure(source=None,runtime=Path('/run/wallaby-agent-secure')):
    if os.geteuid()!=0:raise SystemExit('Installer administrator privileges required.')
    helpers=runpy.run_path(str(source or Path(__file__).with_name('secure-start')))
    prepare=helpers['rename_paths']
    if not runtime.exists():return
    for directory in runtime.iterdir():
        if not directory.name.isdecimal() or int(directory.name)<1000 or directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid!=0:continue
        uid=int(directory.name)
        try:account=pwd.getpwuid(uid)
        except KeyError:continue
        prepare(uid,account.pw_dir)
        if helpers.get('retirement_paths'):helpers['retirement_paths'](uid,account.pw_dir)
if __name__=='__main__':configure()
