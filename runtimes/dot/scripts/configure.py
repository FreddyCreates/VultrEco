#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dot.core import load_config

p=argparse.ArgumentParser(description='Create an exact-version Dot host configuration')
p.add_argument('--image-receipt',required=True)
p.add_argument('--codex-version')
p.add_argument('--gemini-version')
p.add_argument('--out',default='config.json')
a=p.parse_args()
out=Path(a.out)
if out.exists():raise SystemExit('Config already exists; edit it explicitly rather than overwrite it')
image=json.loads(Path(a.image_receipt).read_text())
def release(package,value):
    return value or subprocess.check_output(['npm','view',package,'version'],text=True,timeout=30).strip()
config={'state_dir':'/var/lib/itsnotai-dot','vm_root':'/var/lib/libvirt/images/itsnotai-dot',
        'image':image['path'],'image_sha256':image['sha256'],
        'codex_version':release('@openai/codex',a.codex_version),
        'gemini_version':release('@google/gemini-cli',a.gemini_version),
        'network':'default','gateway':'192.168.122.1','subnet':'192.168.122.0/24',
        'qemu_user':'libvirt-qemu','max_agents':8,'max_vcpus':16,'max_memory_mb':32768,'max_disk_gb':400}
if image.get('kernel_release'):config['expected_kernel']=image['kernel_release']
out.write_text(json.dumps(config,indent=2))
try:load_config(out)
except Exception:
    out.unlink();raise
print('Configuration created:',out.resolve())
