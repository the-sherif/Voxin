#!/usr/bin/env python3
import os
import sys

PID_FILE = os.path.expanduser("~/.voxin.pid")

if not os.path.exists(PID_FILE):
    print("Voxin не запущен", file=sys.stderr)
    sys.exit(1)

with open(PID_FILE) as f:
    pid = int(f.read().strip())

os.kill(pid, 10)  # SIGUSR1
