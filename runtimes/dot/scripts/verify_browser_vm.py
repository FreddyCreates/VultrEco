#!/usr/bin/env python3
"""Run the optional browser probe inside a new credential-free Linux VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


def verify(kernel,initrd,toolchain,out):
    kernel,initrd,toolchain,out=[Path(p).resolve() for p in (kernel,initrd,toolchain,out)]
    out.mkdir(parents=True,exist_ok=False)
    disk=out/'browser.raw'
    with disk.open('xb') as stream:stream.truncate(256*1024*1024)
    subprocess.run(['mkfs.ext4','-F','-q',str(disk)],check=True)
    env=dict(os.environ,LD_LIBRARY_PATH=str(toolchain/'usr/lib/x86_64-linux-gnu'),QEMU_MODULE_DIR=str(toolchain/'usr/lib/x86_64-linux-gnu/qemu'))
    vm_uuid=str(uuid.uuid4())
    command=[str(toolchain/'usr/bin/qemu-system-x86_64'),'-machine','q35,accel=tcg','-cpu','max','-smp','4','-m','4096',
        '-nodefaults','-display','none','-monitor','none','-serial','stdio','-nic','none','-no-reboot',
        '-uuid',vm_uuid,'-L',str(toolchain/'usr/share/qemu'),'-bios',str(toolchain/'usr/share/seabios/bios-256k.bin'),
        '-kernel',str(kernel),'-initrd',str(initrd),'-append','console=ttyS0 rdinit=/init panic=-1 dotvm=browser-probe',
        '-drive','file='+str(disk)+',if=virtio,format=raw']
    log=out/'console.log'
    with log.open('w') as stream:completed=subprocess.run(command,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    text=log.read_text(errors='replace')
    proofs=[json.loads(line.split('DOT_BROWSER_PROOF ',1)[1]) for line in text.splitlines() if 'DOT_BROWSER_PROOF ' in line]
    if completed.returncode or not proofs:raise RuntimeError('Browser guest probe failed; inspect '+str(log))
    result=proofs[-1]
    result.update(vm_uuid=vm_uuid,serial_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
        initramfs_sha256=hashlib.file_digest(initrd.open('rb'),'sha256').hexdigest(),
        kernel_sha256=hashlib.file_digest(kernel.open('rb'),'sha256').hexdigest())
    (out/'receipt.json').write_text(json.dumps(result,indent=2))
    for name in ('desktop.png','mobile.png'):
        subprocess.run(['debugfs','-R','dump /'+name+' '+str(out/name),str(disk)],check=True,capture_output=True)
        if hashlib.sha256((out/name).read_bytes()).hexdigest()!=result['screenshots'][name]:raise ValueError('Screenshot evidence mismatch')
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kernel',required=True);p.add_argument('--initrd',required=True);p.add_argument('--toolchain',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();verify(a.kernel,a.initrd,a.toolchain,a.out)
