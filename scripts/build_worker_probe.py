#!/usr/bin/env python3
"""Prepare a disposable Linux VM for real per-job Docker worker acceptance.

Requires operator-downloaded QEMU/BusyBox, Docker static binaries and Python
worker dependencies. Never includes the controller's keys or provider caches.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile


def pack(root, out):
    raw=out/'worker.cpio';archive=out/'worker.cpio.gz'
    with raw.open('wb') as stream:
        number=0
        def entry(name,mode,data=b'',major=0,minor=0):
            nonlocal number
            number+=1;encoded=name.encode()+b'\0';fields=[number,mode,0,0,1,0,len(data),0,0,major,minor,len(encoded),0]
            stream.write(b'070701'+b''.join(f'{v:08x}'.encode() for v in fields)+encoded+b'\0'*((-(110+len(encoded)))%4))
            stream.write(data+b'\0'*((-len(data))%4))
        for path in sorted(root.rglob('*')):
            name=str(path.relative_to(root));mode=path.lstat().st_mode
            if name=='tmp':mode=stat.S_IFDIR|0o1777
            data=os.readlink(path).encode() if path.is_symlink() else path.read_bytes() if path.is_file() else b''
            entry(name,mode,data)
        entry('dev/console',stat.S_IFCHR|0o600,major=5,minor=1);entry('dev/null',stat.S_IFCHR|0o666,major=1,minor=3);entry('TRAILER!!!',0)
    with archive.open('wb') as target:subprocess.run(['gzip','-1','-c',str(raw)],stdout=target,check=True)
    subprocess.run(['gzip','-t',str(archive)],check=True);raw.unlink()
    return archive


def build(project,out,toolchain,docker,dependencies,token):
    project,out,toolchain,docker,dependencies=[Path(p).resolve() for p in (project,out,toolchain,docker,dependencies)]
    spec=importlib.util.spec_from_file_location('dot_probe_builder',project/'runtimes/dot/scripts/build_probe_root.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    builder.build(out,toolchain,project/'runtimes/dot')
    root=out/'guest-root'
    # The container image contains only Python and required libraries, no service token.
    image=out/'container-image.tar'
    (root/'usr/bin/python').symlink_to('python3.12')
    with tarfile.open(image,'w') as archive:
        for name in ('bin','usr','lib','lib64','etc'):
            if (root/name).exists():archive.add(root/name,arcname=name)
        for name,mode in (('work',0o755),('tmp',0o1777),('proc',0o755),('sys',0o755),('dev',0o755)):
            item=tarfile.TarInfo(name);item.type=tarfile.DIRTYPE;item.mode=mode;archive.addfile(item)
    shutil.copy2(image,root/'container-image.tar')
    for path in docker.iterdir():
        if path.is_file():
            target=root/'bin'/path.name
            shutil.copy2(path,target);target.chmod(0o755)
    shutil.copytree(dependencies,root/'site',ignore=shutil.ignore_patterns('__pycache__'))
    # Native pydantic extensions may have shared dependencies.
    for native in (root/'site').rglob('*.so'):
        output=subprocess.run(['ldd',str(native)],capture_output=True,text=True).stdout
        for value in re.findall(r'(/[^\s()]+)',output):
            source=Path(value);target=root/str(source).lstrip('/')
            if source.is_file() and not target.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    (root/'worker').mkdir();shutil.copy2(project/'worker_runtime.py',root/'worker/worker_runtime.py')
    (root/'worker/probe.py').write_text('''import os,json,subprocess,pathlib
from worker_runtime import app,auth
from fastapi import Header
@app.get('/probe/proof')
def proof(authorization:str|None=Header(None)):
 auth(authorization)
 active=subprocess.check_output(['/bin/docker','ps','-q'],text=True).split()
 log=pathlib.Path('/data/docker-calls.jsonl')
 return {'kernel':os.uname().release,'uid':os.getuid(),'active_containers':active,
  'calls':[json.loads(x) for x in log.read_text().splitlines()] if log.exists() else [],
  'docker_version':subprocess.check_output(['/bin/docker','--version'],text=True).strip(),
  'cgroup_controllers':pathlib.Path('/sys/fs/cgroup/cgroup.controllers').read_text().strip()}
@app.post('/probe/finish')
def finish(authorization:str|None=Header(None)):
 auth(authorization);pathlib.Path('/data/probe-done').write_text('done');return {'stopping':True}
''')
    (root/'worker-bin').mkdir()
    (root/'worker-bin/docker').write_text('''#!/usr/bin/python3
import os,sys,json
with open('/data/docker-calls.jsonl','a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
os.execv('/bin/docker',['docker']+sys.argv[1:])
''');(root/'worker-bin/docker').chmod(0o755)
    (root/'bin/sleep').symlink_to('busybox');(root/'bin/udhcpc').symlink_to('busybox')
    (root/'etc/udhcpc.script').write_text('#!/bin/sh\nif [ "$1" = bound ]; then ip addr add "$ip/24" dev "$interface"; ip route add default via $router; fi\n')
    (root/'etc/udhcpc.script').chmod(0o755)
    init='''#!/bin/sh
export PATH=/bin:/usr/bin
export DOCKER_HOST=unix:///run/docker.sock
chmod 755 /bin/containerd /bin/containerd-shim-runc-v2 /bin/runc /bin/docker* /bin/ctr
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs dev /dev
mkdir -p /dev/pts /dev/shm /sys/fs/cgroup
mount -t devpts devpts /dev/pts
mount -t tmpfs tmpfs /dev/shm
mount -t cgroup2 none /sys/fs/cgroup
chmod 1777 /tmp
ip link set lo up
ip link set eth0 up
udhcpc -i eth0 -s /etc/udhcpc.script -n -q
mount -t ext4 /dev/vda /data || poweroff -f
/bin/busybox rm -f /data/probe-done
mkdir -p /data/runs
chown 1000:1000 /data /data/runs /home/dot
dockerd --data-root=/data/docker --exec-root=/run/docker --storage-driver=vfs --iptables=false --ip-forward=false --ip-masq=false --bridge=none --exec-opt native.cgroupdriver=cgroupfs --host=unix:///run/docker.sock > /data/dockerd.log 2>&1 &
while [ ! -S /run/docker.sock ]; do sleep 1; done
while ! /bin/docker info > /dev/null 2>&1; do sleep 1; done
/bin/docker import /container-image.tar capsula-verifier:local
chown 1000:1000 /run/docker.sock
export PYTHONPATH=/worker:/site HOME=/home/dot
export CAPSULA_WORKER_TOKEN=TOKEN_VALUE
export CAPSULA_WORKER_HOST_RUN_PATH=/data/runs CAPSULA_WORKER_CONTAINER_RUN_PATH=/data/runs CAPSULA_WORKER_SANDBOX_IMAGE=capsula-verifier:local
export PATH=/worker-bin:/bin:/usr/bin
echo CAPSULA_WORKER_VM_READY
python3 -B -c 'import os,uvicorn;os.setgid(1000);os.setuid(1000);uvicorn.run("probe:app",host="0.0.0.0",port=8081,log_level="error")' &
while [ ! -f /data/probe-done ]; do sleep 1; done
sync
poweroff -f
'''.replace('TOKEN_VALUE',token)
    # pivot_root cannot operate from Linux's special initramfs rootfs. Move to
    # the actual ext4 disk before starting Docker; do not weaken its pivot mode.
    stage2=init.replace('mount -t ext4 /dev/vda /data || poweroff -f','mkdir -p /data')
    (root/'init-stage2').write_text(stage2);(root/'init-stage2').chmod(0o755)
    stage1='''#!/bin/sh
export PATH=/bin:/usr/bin
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs dev /dev
mkdir -p /newroot
mount -t ext4 /dev/vda /newroot || poweroff -f
for name in bin usr lib lib64 etc worker worker-bin site home; do /bin/busybox cp -a /$name /newroot/; done
/bin/busybox cp /container-image.tar /init-stage2 /newroot/
mkdir -p /newroot/proc /newroot/sys /newroot/dev /newroot/tmp /newroot/run /newroot/data
chmod 1777 /newroot/tmp
mount --move /proc /newroot/proc
mount --move /sys /newroot/sys
mount --move /dev /newroot/dev
exec /bin/busybox switch_root /newroot /init-stage2
'''
    (root/'init').write_text(stage1);(root/'init').chmod(0o755)
    return pack(root,out)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('project','out','toolchain','docker','dependencies','token-file'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args();token=Path(args.token_file).read_text().strip()
    if not re.fullmatch('[A-Za-z0-9_-]{32,100}',token):raise ValueError('Probe token must be a generated URL-safe secret')
    print(build(args.project,args.out,args.toolchain,args.docker,args.dependencies,token))
