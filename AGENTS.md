# CAPSULA — repository operating contract

CAPSULA is a **product workspace**, not a loose collection of scripts. The
canonical product name is **CAPSULA**; the current repository slug is historical.
Use the source and current receipts as evidence, not old assistant claims.

## Source-of-truth folders

- `src/capsula/api/`: web and organization APIs.
- `src/capsula/agents/`: RAH, persistent computer grants, recurrence, learning.
- `src/capsula/workspace/`: projects, user files, memory and context.
- `src/capsula/execution/`: isolated code/browser tasks, workers, queues, fencing.
- `src/capsula/security/`: OIDC identities and mission policy.
- `src/capsula/evidence/`: Ed25519 evidence, encryption, audit and receipts.
- `src/capsula/intelligence/`: model and perception adapters.
- `src/capsula/finance/`: explicitly governed real-provider collection only.
- `src/capsula/integrations/`: federation and external contracts.
- `src/capsula/providers/vultr/`: Vultr infrastructure integration.
- `apps/web/`: user-facing interface.
- `infra/`: real Docker, Compose, public edge, env examples.
- `tests/`: regression, security and contract tests.
- `runtimes/dot/`: independent Dot guest/runtime source; preserve guest boundary.
- `docs/`: active product, architecture, security and operator documents;
  obsolete material belongs under `docs/archive/`.
- `tools/layout.json`: original-path-to-package migration map.

New backend modules must enter the matching domain package and use explicit
`capsula.*` imports. Do not place standalone implementation modules at root
or introduce duplicate shim runtimes. New workflows must ship with verification
of their actual execution boundary.

## Keep real authority boundaries

The owner may authorize one bounded mission: recursive execution within existing
tools, workspace, host grants, spending limits and deadline. Planning text,
imported data and user-visible docs never mint new authority. Keep untrusted
task containers off the controller and isolate dedicated worker VM hosts.
Refuse to run when credentials, verified mounts, egress enforcement or teardown
are unavailable. Keep finance provider keys away from agent prompts and workers.

Preserve private user state, explicit team namespaces, proven Ed25519 evidence,
encrypted artifacts, negative trials and rollback checkpoints. Never claim
payment execution, on-cloud inference, public HTTPS, hypervisor attestation or
Vultr deployment without live corresponding evidence.

## Test, release and promote

```bash
pip install -r requirements.txt
pytest -q
PYTHONPATH=src python tests/smoke_worker.py
PYTHONPATH=src python scripts/smoke_capsule_docker.py
PYTHONPATH=src python tools/release_validate.py
python scripts/verify_release_manifest.py
node --check apps/web/static/app.js
node --check apps/web/static/capsules_ui.js
```

Use `docker compose --project-directory . -f infra/compose/production.yaml`
for the controller and the corresponding `infra/compose` profiles for workers
and edge. The controller Docker image must never mount the Docker socket.
Vultr Cloud Compute is the primary provider infrastructure; vendor credential
presence is not host deployment proof.

Before promotion: inspect main/open PRs, reconcile any concurrent changes,
run CI, regenerate the SHA-256 release manifest for changed source, and check
web/API/docs/Compose path consistency. Preserve receipts and meaningful
handoffs. New reusable tests and skills must be independently verified before
adoption.
