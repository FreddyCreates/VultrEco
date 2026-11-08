# CAPSULA — Autonomous Agent Computer Cloud

**Intelligence has a place to work.**  
**Medina Labs · v0.8.0-alpha.1 · Vultr Agent Rush 2026 · Blast Radius Zero + Future of Work**

CAPSULA is a full-stack **agent computing platform powered by Vultr** for this
competition: a mission control plane, persistent Linux computers for agents,
disposable code/browser sandboxes, recursive agent delegation, multi-host
execution queues, encrypted memory and artifacts, approvals, and verifiable
signed results. Agents can write and run code, work in browsers, analyze data,
create files, coordinate workflows, and improve tested procedures within bounded
authority. The product is intentionally broad—not one workflow, one worker, or
one industry.

**Vultr is central to the competition build:** Vultr Cloud Compute supplies the
control-plane and isolated worker/agent-VM hosts; the Vultr API supplies fleet
inventory, provisioning and capacity management; Vultr Serverless Inference is
the designated challenge model lane. The underlying interfaces can also run on
other infrastructure without changing CAPSULA's product model.

**What is verified today:** authenticated Vultr account and instance APIs (HTTP
200); one active `capsula-control` instance in the DFW region; a PostgreSQL
distributed queue tested in GitHub Actions; and a repository with testable,
versioned infrastructure. **What is not yet verified:** application deployment
on that VM, separate live worker VMs, a Serverless Inference response, public
HTTPS, a recorded containment demonstration, or final submission.

> **v0.8 alpha, not v1.0.** Source, tests, and provider account access are
> evidence of implementation; they are not proof of a deployed, isolated,
> publicly reachable multi-tenant production service.

## The two challenge tracks

| Blast Radius Zero | Future of Work |
|---|---|
| Model plans/writes code → disposable Docker capsule → real output and evidence | Agents coordinate multi-step work across computers, documents, research, and services |
| Browser goals → isolated Playwright worker → screenshot → approved vision review | Engineering, data, sales, recruitment, finance, procurement, support, operations and more |
| Network, CPU, memory, time, secret, and lifecycle constraints | Durable missions, human approval, replayable work, encrypted state and audit |
| Vultr VM controller and VM workers, Vultr Serverless Inference | Vultr-hosted application, distributed job orchestration and enterprise identity |

One hackathon submission may choose a primary track; the platform supports
both without shrinking its capabilities.

## Vultr integration status

| Component | Current evidence | Release gate |
|---|---|---|
| Cloud API | Account and VM inventory requests returned HTTP 200 | **Connected** |
| Control VM | `capsula-control`, DFW, reported active by Vultr | CAPSULA installation and health pending |
| Multi-host provisioning | `fleet_provider.py` and approved GitHub Actions workflow | Paid creation not executed |
| Distributed control plane | PostgreSQL claims, retries, fencing and OIDC-scoped cluster API | GitHub CI passed; production DB not provisioned |
| Execution workers | Dedicated worker code and disposable Docker sandboxes | Real worker VM/container containment pending |
| Serverless Inference | Vultr OpenAI-compatible model integration implemented | Separate inference secret absent at last preflight |
| HTTPS public app | Pinned SSH deploy and optional Caddy edge workflow | Domain, host credentials and public response pending |
| Evidence | Ed25519, AES-256-GCM, Merkle receipts and offline verifiers | External witness/hardware attestation pending |

**Review and deploy:** [main source](https://github.com/FreddyCreates/VultrEco),
[CI runs](https://github.com/FreddyCreates/VultrEco/actions),
[Vultr preflight](https://github.com/FreddyCreates/VultrEco/actions/workflows/vultr-preflight.yml),
[deploy existing Vultr VM](https://github.com/FreddyCreates/VultrEco/actions/workflows/vultr-existing-deploy.yml),
[full submission gate](hackathon/RELEASE_GATE.md).



> **Release status:** source-implemented alpha, NOT certified public SaaS.
> Existing single-admin APIs are disabled when enterprise mode is enabled.
> PostgreSQL cluster APIs require properly configured OIDC. Real multi-host
> deployment and VM-isolation claims require separate operator evidence.


## Real Docker acceptance evidence

GitHub CI runs `scripts/smoke_capsule_docker.py`: a real Docker
container reads a CSV under `/inputs`, denies writes to container root,
denies public network access, checks absence of protected environment keys,
writes a result under `/outputs`, verifies the SHA-256 digest and confirms
container destruction. This is **GitHub-runner Docker evidence**, not Vultr
VM isolation or independent hypervisor attestation. Repeat on your deployed
Vultr worker VMs using `scripts/benchmark_multi_vm.py`.

## Real work, real computers, real deliverables

From the **Capsules & Deliverables** tab, a workspace owner selects actual
project files, writes or reviews a Python task, and launches it on an approved
isolated worker. A disposable container receives only those read-only files
under `/inputs`; it runs with no network, no controller/provider credentials,
limited CPU/memory/PIDs and read-only root. The task writes results to
`/outputs`. CAPSULA verifies artifact digests, records the worker's teardown
report, encrypts results at rest, provides authenticated file downloads, and
supports discarding the capsule record. If no remote worker is available, it
**fails closed rather than simulating execution**.

The same Python/file envelope is accepted by the tenant-scoped distributed
cluster API and its PostgreSQL worker runner (128 KiB queued payload and
bounded output size in this alpha). This lets external applications build
real engineering, file-fixing, analytics, quality-control and research
workflows without changing CAPSULA's core platform.

## Real-world finance API (operator-controlled, no fake money)

The new `/api/v1/finance` API provides organization-scoped USD receivables
and **Stripe-hosted Checkout**. OIDC `operator` can create an invoice;
OIDC `viewer` can inspect it; only OIDC `admin` can create its payment
session. Payment completion is recorded **only** from a verified Stripe HMAC
webhook with exact invoice, tenant, session, amount, currency and paid status
matching. Idempotency and replay rejection are durable in PostgreSQL. The
Stripe secret stays in the controller, not in a worker, agent, model or UI.

Provide `CAPSULA_STRIPE_SECRET_KEY`,
`CAPSULA_STRIPE_WEBHOOK_SECRET`, and a pinned HTTPS
`CAPSULA_FINANCE_PUBLIC_ORIGIN` to activate merchant collection. Without
them, payment collection fails closed. **Payouts, custody, card issuing,
wallet signing, bank transfers and on-chain settlement are NOT enabled** by
this integration. Consult your provider's onboarding and regulatory terms.

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
| **Cloud fleet** | **Vultr Cloud Compute fleet creation, idempotency, budget ceilings and SSH-only bootstrap** | **v0.7 provider adapter; no automatic paid action** |
| **Enterprise identity** | **OIDC RS256 issuer/audience/JWKS pinning, tenant claim, operator/admin/viewer roles** | **New cluster APIs only; legacy routes disabled in enterprise mode** |
| Intelligence | Local/remote inference, model-generated plans, vision, Vultr Serverless Inference for challenge; local models optional | Requires authorized real provider |
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

## Local development lane — mirrors the Vultr runtime

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

## Vultr infrastructure — the competition deployment

The Vultr API is connected for verified account/instance discovery.
Vultr Cloud Compute is the target infrastructure for controller, worker and
agent-computer VMs; Vultr Serverless Inference is the target model provider.
The `fleet_provider.py` adapter plans multiple Vultr instances against the
live price catalog and enforces an explicit monthly budget. No API token is placed in cloud-init; admission occurs after
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


## Cryptographic provenance

CAPSULA's execution and governance records use **Ed25519** signatures; encrypted project memory and artifacts use **AES-256-GCM**. This provides local-key provenance and authenticated confidentiality, not external attestation or proof against a compromised host.

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

The platform can federate with the canonical `ItsNotAILABS/CAPSULA` engine with
NEXUS, Loom Cluster, POCKET Agent, NOVA Runtime, LiveVault, PARRALAX and
Triple-MCP by explicit contracts—not by pretending all providers are online.

## Real multi-VM acceptance harness

Run `python scripts/benchmark_multi_vm.py` **only** with two or more actual
independent HTTPS worker endpoints, per-host bearer credentials supplied through
environment variables, `CAPSULA_WORKER_NODE_ID` set on each worker and explicit
`CAPSULA_LIVE_VM_TEST_APPROVED=1`. The harness invokes disposable code
containers, checks failed network/root writes and credential absence, and
records latency and cgroup limits. Endpoint behavior alone does not prove
hypervisor separation or hardware attestation. Details: [measurements](docs/MEASUREMENTS.md).

## Deploy onto the existing capsula-control VM

CAPSULA detected an **active `capsula-control` VM in Vultr DFW** through a
read-only GitHub Actions preflight. This is a provider instance fact, **not** a
verified application deployment. To install the reviewed main commit, use the
manual [existing-VM deployment workflow](.github/workflows/vultr-existing-deploy.yml)
with environment protection and pinned SSH host identity. Required GitHub
secrets: `CAPSULA_DEPLOY_SSH_KEY`, `CAPSULA_SSH_KNOWN_HOSTS`, and
`CAPSULA_ADMIN_API_KEY`. Set repository variable
`CAPSULA_DEPLOY_SSH_USER` and optionally `CAPSULA_PUBLIC_FQDN` after DNS is
configured. No cloud token is injected onto the VM, and Docker Compose keeps
the controller bound to loopback unless TLS Caddy ingress is deliberately enabled.
The workflow verifies the exact Git commit and the running CAPSULA health
endpoint; a public URL is claimed only after HTTPS health verification.
