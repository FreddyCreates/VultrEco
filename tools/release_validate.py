"""CAPSULA source-layout integrity and import contract checks.

This validates checked-out source only; it is not a Vultr deployment claim.
"""
from pathlib import Path
import ast, importlib, json, tomllib

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"src"/"capsula"
WEB=ROOT/"apps"/"web"/"static"
DOCS=ROOT/"docs"
required=[
    "src/capsula/api/app.py",
    "src/capsula/api/capsule_api.py",
    "src/capsula/api/cluster_api.py",
    "src/capsula/agents/autonomy.py",
    "src/capsula/agents/computers.py",
    "src/capsula/workspace/platform_core.py",
    "src/capsula/execution/worker_runtime.py",
    "src/capsula/execution/cluster_queue.py",
    "src/capsula/execution/capsule_runtime.py",
    "src/capsula/evidence/proof.py",
    "src/capsula/security/cluster_auth.py",
    "src/capsula/finance/finance_rails.py",
    "src/capsula/intelligence/inference.py",
    "src/capsula/providers/vultr/vultr_cloud.py",
    "src/capsula/providers/vultr/fleet_provider.py",
    "apps/web/static/index.html",
    "apps/web/static/app.js",
    "apps/web/static/capsules_ui.js",
    "infra/compose/production.yaml",
    "infra/compose/worker.yaml",
    "infra/docker/controller.Dockerfile",
    "infra/docker/worker.Dockerfile",
    "infra/edge/Caddyfile",
    "tools/layout.json",
    "docs/architecture/OVERVIEW.md",
    "docs/operations/DEPLOYMENT.md",
    "docs/security/WORKER_SECURITY.md",
    "README.md",
    "VERSION",
    "pyproject.toml",
    ".github/workflows/ci.yml",
]
for rel in required:
    p=ROOT/rel
    assert p.is_file() and p.stat().st_size>0,rel

layout=json.loads((ROOT/"tools"/"layout.json").read_text())
for old,new in layout["layout"].items():
    assert not (ROOT/old).exists(),f"unmigrated loose file: {old}"
    assert (ROOT/new).is_file(),f"missing moved file: {new}"

source=list(SRC.rglob("*.py"))
for p in source+list((ROOT/"tests").rglob("*.py"))+list((ROOT/"scripts").rglob("*.py")):
    ast.parse(p.read_text(),filename=str(p))
assert (ROOT/"VERSION").read_text().strip()=="0.8.0-alpha.1"
assert tomllib.loads((ROOT/"pyproject.toml").read_text())["project"]["version"]=="0.8.0a1"

readme=(ROOT/"README.md").read_text()
for word in ("Vultr","CAPSULA","Ed25519","AES-256-GCM","NEXUS","LiveVault"):
    assert word in readme,word
assert "competition" not in readme.lower()
controller=(ROOT/"infra"/"docker"/"controller.Dockerfile").read_text()
assert "capsula.api.app:app" in controller
assert "docker.sock" not in (ROOT/"infra"/"compose"/"production.yaml").read_text()
assert "CAPSULA_WORKER_TOKEN" in (ROOT/"infra"/"compose"/"worker.yaml").read_text()
assert "network-level egress" in (ROOT/"docs"/"security"/"WORKER_SECURITY.md").read_text()
print(json.dumps({"product":"CAPSULA","version":"0.8.0-alpha.1",
                  "required_files":len(required),"relocated_files":len(layout["layout"]),
                  "source_modules":len(source),"status":"PASS",
                  "vultr_deployment_verified":False},sort_keys=True))
