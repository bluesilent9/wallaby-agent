#!/usr/bin/python3
"""systemd ExecStop: wait for RAM cleanup while the main inhibitor is still held."""
import socket,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from protected_memory import root
with socket.socket(socket.AF_UNIX) as sock:
    sock.settimeout(85);sock.connect(str(root()/'supervisor.sock'));sock.sendall(b'STOP')
    if sock.recv(16)!=b'CLEAN':raise SystemExit('Protected cleanup did not finish.')
