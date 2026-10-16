#!/usr/bin/env python3
"""Heuristic tracked-file hygiene; not a comprehensive secret scanner."""
import re
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
fail=[]
for name in filter(None,files):
    p=root/name
    if any(part in ['.venv','target','AGENTS.md','.codex','.agents','codex-notes','backups'] for part in p.relative_to(root).parts) or name.startswith('results/local/'):
        fail.append(name+': forbidden path')
    data=p.read_bytes()
    if len(data)>10*1024*1024: fail.append(name+': unexpectedly large file')
    try: text=data.decode()
    except UnicodeDecodeError:
        fail.append(name+': binary file');continue
    patterns=[r'/Users/[A-Za-z_][A-Za-z0-9_-]+/',r'/home/[A-Za-z_][A-Za-z0-9_-]+/',r'-----BEGIN [A-Z ]*PRIVATE KEY-----',r'gh[pousr]_[A-Za-z0-9]{20,}',r'github_pat_[A-Za-z0-9_]{20,}',r'AKIA[A-Z0-9]{16}']
    # Do not scan the scanner's literal examples as credentials/paths.
    if name!='tools/publication_check.py' and any(re.search(pattern,text) for pattern in patterns):fail.append(name+': private-path/secret pattern')
assert not fail, '\n'.join(fail)
print(f'Tracked-file hygiene passed ({len(list(filter(None,files)))} files); heuristic scope only.')
