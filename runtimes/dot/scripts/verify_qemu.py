#!/usr/bin/env python3
"""Boot two real Linux guests twice; preserve serial proofs and per-VM disks.

Uses software CPU emulation and no network. This is separate from libvirt/KVM
and provider acceptance; successful local boots do not prove those paths.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


def verify(kernel, initrd, qemu, toolchain, out):
    kernel, initrd, qemu, toolchain, out = [Path(p).resolve() for p in (kernel,initrd,qemu,toolchain,out)]
    out.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,LD_LIBRARY_PATH=str(toolchain/'usr/lib/x86_64-linux-gnu'),QEMU_MODULE_DIR=str(toolchain/'usr/lib/x86_64-linux-gnu/qemu'))
    receipt={'schema':'dot.real-qemu-acceptance.v1','acceleration':'TCG (CPU emulation)',
        'hardware_kvm_verified':False,'libvirt_provisioning_verified':False,
        'provider_inference_verified':False,'browser_render_verified':False,
        'kernel_sha256':hashlib.file_digest(kernel.open('rb'),'sha256').hexdigest(),
        'initramfs_sha256':hashlib.file_digest(initrd.open('rb'),'sha256').hexdigest(),'boots':[]}
    for label in ('agent-a','agent-b'):
        disk=out/(label+'.raw')
        with disk.open('xb') as file:file.truncate(256*1024*1024)
        subprocess.run(['mkfs.ext4','-F','-q',str(disk)],check=True)
        vm_uuid=str(uuid.uuid4())
        for boot in (1,2):
            log=out/(label+'-boot-'+str(boot)+'.log')
            command=[str(qemu),'-machine','q35,accel=tcg','-cpu','max','-smp','4','-m','2048',
                '-nodefaults','-display','none','-monitor','none','-serial','stdio','-nic','none','-no-reboot',
                '-uuid',vm_uuid,'-L',str(toolchain/'usr/share/qemu'),
                '-bios',str(toolchain/'usr/share/seabios/bios-256k.bin'),
                '-kernel',str(kernel),'-initrd',str(initrd),
                '-append','console=ttyS0 rdinit=/init panic=-1 dotvm='+label,
                '-drive','file='+str(disk)+',if=virtio,format=raw']
            with log.open('w') as stream:
                completed=subprocess.run(command,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
            text=log.read_text(errors='replace')
            results=[line.split('DOT_PROBE_RESULT ',1)[1] for line in text.splitlines() if 'DOT_PROBE_RESULT ' in line]
            proof=json.loads(results[-1]) if results else None
            receipt['boots'].append({'vm':label,'uuid':vm_uuid,'boot':boot,'exit_code':completed.returncode,
                'proof':proof,'serial_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
            receipt['status']='in_progress'
            (out/'receipt.json').write_text(json.dumps(receipt,indent=2))
            if completed.returncode or not proof:
                raise RuntimeError('Guest acceptance failed; inspect '+str(log))
            expected='promoted_before_reboot' if boot==1 else 'reboot_persistence_and_rollback_verified'
            if proof['phase']!=expected or proof['uid']!=1000:
                raise RuntimeError('Guest proof mismatch')
            print(label,'boot',boot,proof['phase'],flush=True)
    first=[b for b in receipt['boots'] if b['boot']==1]
    if len({b['uuid'] for b in first})!=2 or len({b['proof']['boot_id'] for b in receipt['boots']})!=4:
        raise RuntimeError('Guest/kernel identity separation failed')
    receipt['status']='two_vms_reboot_and_improvement_verified'
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2))
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kernel',required=True);p.add_argument('--initrd',required=True);p.add_argument('--qemu',required=True);p.add_argument('--toolchain',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps(verify(a.kernel,a.initrd,a.qemu,a.toolchain,a.out),indent=2))
