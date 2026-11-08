"""Verify all files committed in CAPSULA's release manifest."""
from __future__ import annotations
import hashlib, json, pathlib, sys
root = pathlib.Path(__file__).resolve().parent.parent
manifest = json.loads((root/'release-manifest.json').read_text())
errors=[]
for record in manifest['files']:
    path=root/record['path']
    if not path.is_file():errors.append(f"missing: {record['path']}");continue
    content=path.read_bytes()
    if len(content)!=record['bytes'] or hashlib.sha256(content).hexdigest()!=record['sha256']:
        errors.append(f"mismatch: {record['path']}")
print(json.dumps({'version':manifest['version'],'verified_files':len(manifest['files'])-len(errors),'errors':errors,'status':'FAIL' if errors else 'PASS'}))
sys.exit(bool(errors))
