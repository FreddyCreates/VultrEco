# CAPSULA — Autonomous Computer Cloud

**Intelligence has a place to work.**  
Medina Labs · **v0.7.0-alpha.1** · Provider-independent agent infrastructure

CAPSULA is a computing platform where humans, applications and autonomous agents
create durable workspaces, provision dedicated computers, delegate bounded work
to fleets of isolated executors, preserve verifiable evidence and learn from
measured outcomes. It is not a single worker, a finance app or a Vultr wrapper.

> **Release status:** source-implemented alpha, NOT certified public SaaS.
> Existing single-admin APIs are disabled when enterprise mode is enabled.
> PostgreSQL cluster APIs require properly configured OIDC. Real multi-host
> deployment and VM-isolation claims require separate operator evidence.

## Platform planes

| Plane | What CAPSULA has | v0.7 status |
|---|---|---|
| Human & agent work | Projects, encrypted revisions, persistent goals, agent profiles | Implemented / locally tested |
| Dedicated computers | Each Dot agent may bind a unique KVM/libvirt VM and credential store | Source integrated; hardware host acceptance outstanding |
| Recursive Agentic Hierarchy | Bounded mission tree, distinct VM grants, checkpoints, handoffs | Source contracts and tests |
| Disposable capsules | Per-job Docker Python and read-only Playwright browser agents | Local containment receipts; external worker proof required |
| Shared compute | Multiple registered worker hosts, capacity, draining, utilization-aware placement | SQLite single-authority fleet implemented |
| **Cluster scheduling** | **PostgreSQL transactions, SKIP LOCKED claims, retry/dead-letter, lease epochs + fencing** | **v0.7 integration tests; not global consensus** |
| **Cluster runner** | **A separate host pulls DB jobs and sends work only to its local isolated executor** | **v0.7 runner; requires private network and real worker deployment** |
| **Cloud fleet** | **Vultr planned multi-host creation, idempotency, cost ceilings and SSH-only bootstrap** | **v0.7 provider adapter; no automatic paid action** |
| **Enterprise identity** | **OIDC RS256 issuer/audience/JWKS pinning, tenant claim, operator/admin/viewer roles** | **New cluster APIs only; legacy routes disabled in enterprise mode** |
| Intelligence | Local/remote inference, model-generated plans, vision, optional Vultr Serverless Inference | Requires authorized real provider |
| Evidence & memory | Encrypted memory/artifacts, signed execution/governance receipts, offline verification | Source/tests; no external TEE/witness |
| Improvement lab | Repeatable baseline/candidate experiments, versioned skill proposals, rollback | Source/tests, scoped to owned projects |

## Real work flow

```text
Owner / connected application / authorized service
       ↓ identity + workspace permission + mission grant
CAPSULA mission control — planning, budgets, durable memory and approval
       ↓ RAH / workflows / queue
PostgreSQL durable queue  ──────↔  distributed controllers
       ↓ row-locked admission + per-worker lease/fencing token
┌──────────────────────────────────────────────────┐
│ Worker Host A      Worker Host B      Host C      │
│ ├─ disposable OCI  ├─ browser OCI     ├─ Dot VM    │
│ └─ code artifacts  └─ screenshots     └─ agent OS │
└──────────────────────────────────────────────────┘
       ↓ results + acceptance + signed CAPSULA evidence
Artifacts, memory, audit, rollback and next bounded mission
```

## Run CAPSULA locally — no cloud dependency

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export CAPSULA_API_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export CAPSULA_DATA="$PWD/data"
uvicorn app:app --host 127.0.0.1 --port 8080
```

Launch [http://127.0.0.1:8080](http://127.0.0.1:8080).
Local setup supports projects, plans, memory, artifacts and proofs;
actual code/browser execution fails closed without isolated workers.

## Cluster setup — PostgreSQL and OIDC

CAPSULA runs a **separate multi-user cluster API** at `/api/v1/cluster`.
A shared PostgreSQL instance is required for multi-controller admission:

```bash
export CAPSULA_CLUSTER_DATABASE_URL='postgresql://user:password@db-host:5432/capsula?sslmode=verify-full'
python scripts/migrate_cluster.py
```

Configure `CAPSULA_ENTERPRISE_MODE=1`, `CAPSULA_OIDC_ISSUER`,
`CAPSULA_OIDC_AUDIENCE`, and `CAPSULA_OIDC_JWKS_URL` on the controller.
Use an OIDC provider that issues the signed `capsula_tenant` and
`capsula_role` claims. Cluster APIs enforce tenant ownership on every query.
**Do not enable enterprise mode before configuring OIDC and PostgreSQL.**
There is no local-email/password shortcut or mock identity in this mode.
The legacy single-admin surface is not a multi-tenant SaaS.

See [docs/CLUSTER_OPERATIONS.md](docs/CLUSTER_OPERATIONS.md) for API enrollment,
separate worker provisioning and recovery.

## Vultr is pluggable—not the product

Vultr Cloud Compute can host multiple controllers and worker VMs, and Vultr
Serverless Inference can provide models. A separate provider adapter plans
instances against Vultr's live price catalog and enforces an explicit total
monthly budget. No API token is placed in cloud-init; admission occurs after
secure host bootstrap. Do not run paid provisioning from a model-generated
goal or from the public cluster API.

```bash
# Read-only preflight (uses GitHub Actions secret if run in CI)
python scripts/vultr_preflight.py
# Plan only; never creates anything
python scripts/fleet_cli.py plan --prefix capsula --region ewr \
  --plan vc2-1c-2gb --os-id 2284 --ssh-key-id YOUR_EXISTING_ID \
  --role worker --count 3 --max-monthly-usd 100
```

The plan validates instance count, current provider prices and existing labels.
Paid `apply` requires a human-run workflow with budget confirmation and
`CAPSULA_DEPLOY_APPROVED=1`. Cloud-init installs host prerequisites; it does
**not** claim a service is ready or smuggle keys onto a public VM.

## Acceptance gates

Run `pytest -q`, `python release_validate.py`,
`python scripts/verify_release_manifest.py`, and
`python scripts/benchmark_cluster.py` with an actual PostgreSQL service.
The last benchmark measures **database-backed queue admission only**.
Real KVM guests, Vultr VMs, workload isolation, app HTTPS access and inference
are separate tests. See [docs/CLUSTER_OPERATIONS.md](docs/CLUSTER_OPERATIONS.md),
[docs/MEASUREMENTS.md](docs/MEASUREMENTS.md),
[docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) and
[hackathon/RELEASE_GATE.md](hackathon/RELEASE_GATE.md).

**Release gates still open:** public TLS/RBAC review, DB HA/backups, fencing
of remote *execution* after a lost lease, real multi-VM throughput, egress
enforcement, Vultr deployment URL, live Serverless Inference receipts and
recorded containment demonstration. A database lease does not terminate a
potentially still-running process.

The product also integrates the canonical `ItsNotAILABS/CAPSULA` engine with
NEXUS, Loom Cluster, POCKET Agent, NOVA Runtime, LiveVault, PARRALAX and
Triple-MCP by explicit contracts—not by pretending all providers are online.
