#!/usr/bin/env python3
"""Package source using an allowlist; never sweep local runtime state or credentials."""
import hashlib
import json
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parents[1]
version=json.loads((root/'receipts/release.json').read_text())['version']
files=[]
for p in sorted(root.rglob('*')):
    if not p.is_file() or p.is_symlink() or '__pycache__' in p.parts:
        continue
    rel=p.relative_to(root)
    allowed=(len(rel.parts)==1 and (p.suffix=='.md' or p.name=='pyproject.toml')
             or rel.parts[0]=='dot' and p.suffix in ('.py','.js','.css','.html','.json','.txt')
             or rel.parts[0]=='tests' and p.suffix=='.py'
             or rel.parts[0]=='scripts' and p.suffix in ('.py','.sh','.service')
             or rel.parts[0]=='kernel' and (p.suffix=='.config' or str(rel) in ('kernel/bzImage','kernel/probe-initramfs.cpio.gz','kernel/source-info.json','kernel/COPYING') or len(rel.parts)>2 and rel.parts[1] in ('licenses','runtime-licenses'))
             or rel.parts[0]=='docs' and p.suffix=='.md'
             or str(rel) in ('receipts/release.json','receipts/source-validation.json','receipts/local-recovery.json','receipts/self-improvement.json','receipts/session-handoff.json','receipts/kernel-build.json','receipts/qemu-acceptance.json','receipts/browser-acceptance.json','receipts/browser-toolchain.json','receipts/guest-bootstrap-failure.json','receipts/browser-bootstrap-failure.json'))
    if allowed:
        files.append(p)
manifest=[]
for p in files:
    with p.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    manifest.append({'path':str(p.relative_to(root)),'sha256':sha,'size':p.stat().st_size})
(root/'receipts/hash-manifest.json').write_text(json.dumps(manifest,indent=2))
archive=root.parent/f'itsnotai-dot-linux-kernel-v{version}.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files+[root/'receipts/hash-manifest.json']:
        z.write(p,root.name+'/'+str(p.relative_to(root)))
print(archive)
