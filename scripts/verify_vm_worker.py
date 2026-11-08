#!/usr/bin/env python3
"""Boot a fresh private worker VM, run real controller acceptance, shut it down."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request


def verify(kernel,initrd,toolchain,token_file,out):
    kernel,initrd,toolchain,token_file,out=[Path(p).resolve() for p in (kernel,initrd,toolchain,token_file,out)]
    out.mkdir(parents=True,exist_ok=False,mode=0o700)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    disk=out/'worker.raw'
    with disk.open('xb') as stream:stream.truncate(2*1024**3)
    subprocess.run(['mkfs.ext4','-F','-q',str(disk)],check=True)
    endpoint='http://127.0.0.1:'+str(port)
    env=dict(os.environ,LD_LIBRARY_PATH=str(toolchain/'usr/lib/x86_64-linux-gnu'),QEMU_MODULE_DIR=str(toolchain/'usr/lib/x86_64-linux-gnu/qemu'))
    argv=[str(toolchain/'usr/bin/qemu-system-x86_64'),'-machine','q35,accel=tcg','-cpu','max','-smp','4','-m','3072',
        '-nodefaults','-display','none','-monitor','none','-serial','stdio','-no-reboot','-L',str(toolchain/'usr/share/qemu'),
        '-bios',str(toolchain/'usr/share/seabios/bios-256k.bin'),'-kernel',str(kernel),'-initrd',str(initrd),
        '-append','console=ttyS0 rdinit=/init panic=-1','-drive','file='+str(disk)+',if=virtio,format=raw',
        '-netdev',f'user,id=worker,hostfwd=tcp:127.0.0.1:{port}-:8081','-device','virtio-net-pci,netdev=worker,romfile=']
    serial=out/'console.log'
    with serial.open('w') as log:
        vm=subprocess.Popen(argv,env=env,stdout=log,stderr=subprocess.STDOUT)
        child=subprocess.Popen([sys.executable,str(Path(__file__).with_name('verify_clean_worker.py')),
            '--endpoint',endpoint,'--token-file',str(token_file),'--out',str(out/'acceptance'),'--inspect-bootstrap'])
        try:
            deadline=time.monotonic()+500
            while child.poll() is None:
                if vm.poll() is not None:raise RuntimeError('Guest stopped before acceptance; inspect '+str(serial))
                if time.monotonic()>=deadline:raise TimeoutError('Worker acceptance exceeded the total deadline')
                time.sleep(1)
            if child.returncode:raise RuntimeError('Actual worker acceptance failed; inspect private acceptance output')
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=5)
            try:
                req=urllib.request.Request(endpoint+'/probe/finish',method='POST',headers={'Authorization':'Bearer '+token_file.read_text().strip()})
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5)
                vm.wait(timeout=15)
            except Exception:
                vm.terminate();vm.wait(timeout=10)
    receipt=json.loads((out/'acceptance/receipt.json').read_text())
    receipt.update(execution_environment='actual Docker containers in separate QEMU TCG Linux guest',
        kernel_sha256=hashlib.file_digest(kernel.open('rb'),'sha256').hexdigest(),
        initramfs_sha256=hashlib.file_digest(initrd.open('rb'),'sha256').hexdigest(),
        serial_log_sha256=hashlib.sha256(serial.read_bytes()).hexdigest())
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print('Actual isolated worker receipt:',out/'receipt.json')
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('kernel','initrd','toolchain','token-file','out'):p.add_argument('--'+name,required=True)
    args=p.parse_args();verify(args.kernel,args.initrd,args.toolchain,args.token_file,args.out)
