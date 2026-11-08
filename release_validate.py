"""Release contract linter. Local checks only, not live deployment attestation."""
from pathlib import Path
import json,hashlib,ast,tomllib
root=Path(__file__).resolve().parent
required=['app.py','platform_core.py','audit.py','artifacts.py','federation.py','inference.py','nexus_bridge.py','proof.py','policy.py','worker_runtime.py','verify_evidence.py','verify_governance.py','static/index.html','static/app.js','static/app.css','README.md','PRODUCTION.md','DEPLOYMENT.md','WORKER_SECURITY.md','OPERATOR_BOUNDARY.md','ARCHITECTURE.md','VERSION','CHANGELOG.md','Dockerfile.production','docker-compose.production.yml','docker-compose.worker.yml','docker-compose.browser.yml','worker.Dockerfile','browser.Dockerfile','.github/workflows/ci.yml','smoke_worker.py','test_federation_v3.py','test_nexus_bridge.py','test_artifacts_v3.py','test_platform_v4.py']
for rel in required:
    p=root/rel;assert p.is_file() and p.stat().st_size>0,rel
for p in root.glob('*.py'):ast.parse(p.read_text())
assert (root/'VERSION').read_text().strip()=='0.4.0-alpha.1'
assert tomllib.loads((root/'pyproject.toml').read_text())['project']['version']=='0.4.0a1'
readme=(root/'README.md').read_text()
for v in ('NEXUS','Loom Cluster','POCKET Agent','LiveVault','PARRALAX','Triple-MCP','Vultr','Ed25519','AES-256-GCM'):
    assert v in readme,v
assert 'docker.sock' not in (root/'docker-compose.production.yml').read_text()
assert 'CAPSULA_WORKER_TOKEN' in (root/'docker-compose.worker.yml').read_text()
assert 'network-level egress' in (root/'WORKER_SECURITY.md').read_text()
print(json.dumps({'version':'0.4.0-alpha.1','required_release_files':len(required),'python_parsed':len(list(root.glob('*.py'))),'status':'PASS','deployment_or_external_attestation':'NOT PERFORMED'}))
