"""Release contract linter. Local checks only, not live deployment attestation."""
from pathlib import Path
import json,hashlib,ast,tomllib
root=Path(__file__).resolve().parent
required=['capsule_runtime.py', 'capsule_api.py', 'finance_rails.py', 'finance_api.py', 'static/capsules_ui.js', 'test_capsula_v08.py', 'test_finance_cluster_v08.py', 'cluster_queue.py', 'cluster_auth.py', 'cluster_api.py', 'cluster_runner.py', 'fleet_provider.py', 'test_cluster_v07.py', 'test_multi_vm_harness.py', 'test_vultr_deploy_v07.py', 'scripts/deploy_existing_vultr.py', 'docker-compose.edge.yml', 'deploy/Caddyfile', 'scripts/benchmark_multi_vm.py', 'docs/CLUSTER_OPERATIONS.md', 'docs/MEASUREMENTS.md', 'docker-compose.cluster.yml', 'scripts/migrate_cluster.py', 'scripts/benchmark_cluster.py', 'learning.py', 'computers.py', 'improvement_lab.py', 'platform_routes.py', 'test_rah_learning.py', 'app.py', 'platform_core.py', 'audit.py', 'artifacts.py', 'federation.py', 'inference.py', 'nexus_bridge.py', 'proof.py', 'policy.py', 'worker_runtime.py', 'verify_evidence.py', 'verify_governance.py', 'static/index.html', 'static/app.js', 'static/app.css', 'README.md', 'PRODUCTION.md', 'DEPLOYMENT.md', 'WORKER_SECURITY.md', 'OPERATOR_BOUNDARY.md', 'ARCHITECTURE.md', 'VERSION', 'CHANGELOG.md', 'Dockerfile.production', 'docker-compose.production.yml', 'docker-compose.worker.yml', 'docker-compose.browser.yml', 'worker.Dockerfile', 'browser.Dockerfile', '.github/workflows/ci.yml', 'smoke_worker.py', 'test_federation_v3.py', 'test_nexus_bridge.py', 'test_artifacts_v3.py', 'test_platform_v4.py', 'autonomy.py', 'autonomy_daemon.py', 'challenge.py', 'vision.py', 'browser_task.py', 'test_autonomy.py', 'test_browser_vision.py', 'docker-compose.autonomy.yml', 'vultr_cloud.py', 'test_vultr_cloud.py']
for rel in required:
    p=root/rel;assert p.is_file() and p.stat().st_size>0,rel
for p in root.glob('*.py'):ast.parse(p.read_text())
assert (root/'VERSION').read_text().strip()=='0.8.0-alpha.1'
assert tomllib.loads((root/'pyproject.toml').read_text())['project']['version']=='0.8.0a1'
readme=(root/'README.md').read_text()
for v in ('NEXUS','Loom Cluster','POCKET Agent','LiveVault','PARRALAX','Triple-MCP','Vultr','Ed25519','AES-256-GCM'):
    assert v in readme,v
assert 'docker.sock' not in (root/'docker-compose.production.yml').read_text()
assert 'CAPSULA_WORKER_TOKEN' in (root/'docker-compose.worker.yml').read_text()
assert 'network-level egress' in (root/'WORKER_SECURITY.md').read_text()
print(json.dumps({'version':'0.8.0-alpha.1','required_release_files':len(required),'python_parsed':len(list(root.glob('*.py'))),'status':'PASS','deployment_or_external_attestation':'NOT PERFORMED'}))
