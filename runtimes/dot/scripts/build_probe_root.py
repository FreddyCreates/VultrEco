#!/usr/bin/env python3
"""Build a small BusyBox/Python guest initramfs from operator-owned local tools."""
import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess


def build(out, toolchain, project, browser_dir=None, browser_python=None):
    out, toolchain, project = Path(out).resolve(), Path(toolchain).resolve(), Path(project).resolve()
    root = out / 'guest-root'
    root.mkdir(parents=True, exist_ok=False)
    for name in ('bin','sbin','dev','proc','sys','tmp','run','data','home/dot','usr/bin','usr/lib','etc'):
        (root/name).mkdir(parents=True, exist_ok=True)
    busybox = next(p for p in (toolchain/'usr/bin/busybox', toolchain/'bin/busybox') if p.is_file())
    shutil.copy2(busybox, root/'bin/busybox')
    for applet in ('sh','mount','mkdir','ip','chown','chmod','sync','poweroff','cat'):
        (root/'bin'/applet).symlink_to('busybox')
    shutil.copy2('/usr/bin/python3.12',root/'usr/bin/python3.12')
    (root/'usr/bin/python3').symlink_to('python3.12')
    shutil.copytree('/usr/lib/python3.12',root/'usr/lib/python3.12',ignore=shutil.ignore_patterns('__pycache__','test','tests','idlelib','tkinter','ensurepip'))
    queue = [Path('/usr/bin/python3.12')] + list((root/'usr/lib/python3.12').rglob('*.so'))
    if browser_dir or browser_python:
        if not browser_dir or not browser_python:
            raise ValueError('Supply both browser directory and Python Playwright directory')
        shutil.copytree(browser_dir,root/'chrome')
        shutil.copytree(browser_python,root/'browser-python',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree('/usr/share/fonts/truetype',root/'usr/share/fonts/truetype')
        (root/'etc/fonts').mkdir(parents=True)
        shutil.copy2('/etc/fonts/fonts.conf',root/'etc/fonts/fonts.conf')
        queue += [root/'chrome/chrome',root/'chrome/chrome_crashpad_handler',root/'browser-python/playwright/driver/node']
        queue += list((root/'browser-python').rglob('*.so'))
    # Copy transitive dynamic loader dependencies without loading host secrets.
    seen = set()
    while queue:
        file = queue.pop()
        if str(file) in seen: continue
        seen.add(str(file))
        result = subprocess.run(['ldd',str(file)],capture_output=True,text=True)
        for path in re.findall(r'(/[^\s()]+)',result.stdout):
            source = Path(path)
            if not source.is_file(): continue
            target = root / str(source).lstrip('/')
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
                queue.append(source)
    shutil.copytree(project/'dot',root/'app/dot',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(project/'tests',root/'app/tests',ignore=shutil.ignore_patterns('__pycache__'))
    (root/'app/scripts').mkdir()
    for name in ('probe_guest.py','probe_browser.py','exercise_recovery.py','upgrade_guest.py'):
        shutil.copy2(project/'scripts'/name,root/'app/scripts'/name)
    (root/'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\ndot:x:1000:1000:dot:/home/dot:/bin/sh\n')
    (root/'etc/group').write_text('root:x:0:\ndot:x:1000:\n')
    (root/'etc/hosts').write_text('127.0.0.1 localhost\n')
    (root/'tmp').chmod(0o1777)
    init='''#!/bin/sh
export PATH=/bin:/usr/bin:/sbin
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs dev /dev
mkdir -p /dev/pts /dev/shm
mount -t devpts devpts /dev/pts
mount -t tmpfs tmpfs /dev/shm
chmod 1777 /tmp
ip link set lo up
mount -t ext4 /dev/vda /data || poweroff -f
chown 1000:1000 /data /home/dot
export HOME=/home/dot PYTHONDONTWRITEBYTECODE=1
python3 -B -c 'import os,runpy;os.setgid(1000);os.setuid(1000);runpy.run_path("/app/scripts/probe_guest.py",run_name="__main__")'
echo DOT_GUEST_EXIT=$?
sync
poweroff -f
'''
    (root/'init').write_text(init);(root/'init').chmod(0o755)
    if browser_dir:
        (root/'init').write_text(init.replace('/app/scripts/probe_guest.py','/app/scripts/probe_browser.py'))
    # Portable newc archive: create device metadata without requiring host mknod.
    archive=out/'guest-root.cpio.gz'
    raw_archive=out/'guest-root.cpio'
    with raw_archive.open('wb') as stream:
        inode=0
        def entry(name,mode,data=b'',major=0,minor=0):
            nonlocal inode
            inode+=1;encoded=name.encode()+b'\0'
            fields=[inode,mode,0,0,1,0,len(data),0,0,major,minor,len(encoded),0]
            header=b'070701'+b''.join(f'{v:08x}'.encode() for v in fields)
            stream.write(header+encoded+b'\0'*((-(110+len(encoded)))%4));stream.write(data+b'\0'*((-len(data))%4))
        for path in sorted(root.rglob('*')):
            name=str(path.relative_to(root));info=path.lstat()
            data=os.readlink(path).encode() if path.is_symlink() else path.read_bytes() if path.is_file() else b''
            mode=(stat.S_IFDIR|0o1777) if name=='tmp' else info.st_mode
            entry(name,mode,data)
        entry('dev/console',stat.S_IFCHR|0o600,major=5,minor=1)
        entry('dev/null',stat.S_IFCHR|0o666,major=1,minor=3)
        entry('TRAILER!!!',0)
    with archive.open('wb') as target:
        subprocess.run(['gzip','-1','-c',str(raw_archive)],stdout=target,check=True)
    subprocess.run(['gzip','-t',str(archive)],check=True)
    raw_archive.unlink()
    print(archive)
    return archive


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--toolchain',required=True);p.add_argument('--project',required=True)
    p.add_argument('--browser-dir');p.add_argument('--browser-python')
    a=p.parse_args();build(a.out,a.toolchain,a.project,a.browser_dir,a.browser_python)
