<div align="center">

# CAPSULA

### Give intelligence a place to work.

**A computer for every agent. A capsule for every task. Proof for every result.**

*The agent computer cloud — powered by Vultr.*

[Explore the platform](#one-place-to-make-things-happen) · [How it works](#from-intent-to-outcome) · [Architecture](#the-platform) · [Build with CAPSULA](#start-building)

</div>

---

## Intelligence should do more than answer.

An idea arrives. A project begins. A deadline approaches.

You should be able to say what needs to happen, give that work the right tools, and watch it move from intention to completion.

**CAPSULA gives humans and AI agents the computers, workspaces, permissions and infrastructure to get real work done.** An agent can plan a task, open a project, use a temporary computer, write code, work with files, return a deliverable and leave an auditable record. The computer used for the task can then be destroyed.

Not a chat window pretending to execute. Not an endless collection of disconnected automations.

A place where work actually happens.

## One place to make things happen.

| Your world | What CAPSULA provides |
|---|---|
| **Mission Control** | Turn an outcome into bounded plans, delegated tasks, checkpoints, approvals and visible progress. |
| **Agent Computers** | Persistent work environments and dedicated-computer architecture for agents that need continuity across projects. |
| **Disposable Capsules** | Run bounded code or browser work in isolated task environments, then collect results and destroy the environment. |
| **Projects & Workspaces** | Keep files, revisions, context, encrypted memory and team work organized around the work itself. |
| **Intelligence & Perception** | Connect inference providers, including Vultr Serverless Inference, for planning, interpretation and guided tool use. |
| **Evidence & Trust** | Signed execution receipts, cryptographic hashes, audit trails, access controls and explicit approval boundaries. |
| **Connected Operations** | Reusable APIs for engineering, research, analysis, operations and provider-governed financial workflows. |

CAPSULA is designed to move with the user — from one task on one computer to a coordinated network of agents, each with its own responsibilities and limits.

## From intent to outcome.

```text
You describe the outcome
        │
        ▼
CAPSULA Mission Control
Plan · Permissions · Budget · Human approval when needed
        │
        ▼
Assign an agent or a dedicated computer
        │
        ▼
Create a disposable capsule
Real code · Files · Browser tasks · Bounded resources
        │
        ▼
Run the work on an isolated worker
CPU & memory limits · Credential separation · Lifecycle control
        │
        ▼
Return the result
Outputs · Screenshots · Artifacts · Receipts
        │
        ▼
Verify, preserve, learn — and destroy the disposable environment
```

A capsule is a **temporary computing environment**, not a renamed prompt. It has a defined task, bounded resources, isolated input files and a teardown requirement. A durable agent computer is a different thing: it preserves state when persistence is authorized.

That distinction is central to the product.

## CAPSULA × Vultr

CAPSULA is the experience. **Vultr provides the computing foundation that lets it exist beyond a single machine.**

| Layer | How they work together |
|---|---|
| **Vultr Cloud Compute** | Hosts CAPSULA's controller, dedicated execution workers and agent-computer infrastructure. |
| **Vultr infrastructure APIs** | Discover machines, plan new capacity, provision hosts within approved budgets and manage the fleet. |
| **Vultr Serverless Inference** | Supplies an inference lane for model-assisted planning and task interpretation when the service is configured. |
| **CAPSULA Control Plane** | Coordinates workspaces, mission authority, agents, queues, execution leases and result acceptance. |
| **CAPSULA Execution Plane** | Runs disposable task containers on separate worker machines and returns artifacts with cleanup evidence. |
| **CAPSULA Evidence Plane** | Keeps encrypted project data, Ed25519 receipts, AES-256-GCM records and verifiable result hashes. |

**Why this matters:** users experience one coherent product while the infrastructure can expand underneath it. More work can be placed across more computers. Independent worker hosts provide a stronger boundary than running arbitrary tasks in the web application itself. Each task has its own grant, resource limits and recorded outcome.

The architecture keeps Vultr central to the integrated cloud experience while allowing future infrastructure adapters without rewriting what CAPSULA is.

## Built for the real world.

**Build.** Let an agent inspect a codebase, generate a file, run a check, and return the changes for review.

**Understand.** Give CAPSULA a dataset. Run actual analysis, create outputs, and keep the evidence alongside the project.

**Operate.** Coordinate multi-step work across teams, documents, support, procurement, research, engineering and service APIs.

**Delegate.** Give specialized agents bounded missions. Allow recursive execution inside approved tools, workspace, budget and deadline — with human oversight for sensitive actions.

**Protect.** Keep ephemeral jobs separate from account credentials. Require approvals for consequential actions and verify the artifacts returned.

**Move money responsibly.** CAPSULA contains organization-scoped receivables and Stripe-hosted Checkout integration. Payment sessions and settlement require a configured real processor, signed webhooks and authorized users; CAPSULA does not claim custody, payouts or bank transfers.

## The platform

```text
CAPSULA/
├── apps/
│   └── web/                 First-party product interface
├── src/capsula/
│   ├── api/                 Web API, workspaces, capsules, finance, cluster
│   ├── agents/              Mission control, RAH, learning, agent computers
│   ├── workspace/           Projects, files and persistent state
│   ├── execution/           Capsules, isolated workers, distributed queues
│   ├── intelligence/        Inference and vision
│   ├── evidence/            Signed receipts, audit and encrypted artifacts
│   ├── security/            Identity, access and policy
│   ├── finance/             Governed provider-backed payments
│   ├── integrations/        Federation and NEXUS bridges
│   └── providers/vultr/     Vultr fleet and cloud integrations
├── runtimes/dot/            Independent Dot computer runtime
├── infra/
│   ├── compose/             Control plane, workers, browser, edge, cluster
│   ├── docker/              Reproducible service images
│   ├── edge/                HTTPS gateway
│   └── env/                 Configuration examples
├── tests/                   Automated contracts and adversarial tests
├── scripts/                 Provisioning, measurements and verification
├── tools/                   Release integrity and workspace utilities
├── docs/                    Architecture, operation, security and vision
└── receipts/                Collected verification and release evidence
```

<details>
<summary><strong>Engineering architecture</strong></summary>

CAPSULA is intentionally separated into a user-facing **control plane**, a disposable **execution plane**, and an **evidence plane**. The distributed scheduler supports PostgreSQL transactions, worker leases, retry/dead-letter handling and fencing tokens. Enterprise APIs use signed tenant identity and role checks; the legacy operator surface is not represented as multi-tenant.

A worker can execute code in a disposable Docker container with bounded CPU, memory and processes, no task-level cloud credentials, blocked networking and read-only system mounts. It returns actual outputs after cleanup verification. For hostile browsing, independent worker VMs and network-level egress enforcement are additional requirements.

The governing rule is simple: **an agent may act only within its authorized mission.** It cannot obtain broader authority just by writing a more ambitious plan.

[Technical architecture](docs/architecture/OVERVIEW.md) · [Agent system](docs/architecture/AGENTS.md) · [Operations](docs/operations/DEPLOYMENT.md) · [Security](docs/security/WORKER_SECURITY.md)

</details>

## Start building.

Requirements: Python 3.11+, a strong operator API key, and dedicated workers if you intend to execute untrusted code.

```bash
git clone https://github.com/FreddyCreates/VultrEco.git
cd VultrEco
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export CAPSULA_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export CAPSULA_DATA="$PWD/data"
PYTHONPATH=src uvicorn capsula.api.app:app --host 127.0.0.1 --port 8080
```

Open **http://127.0.0.1:8080** and enter your operator key. Project management, memory and planning can run locally. Untrusted code execution **fails closed** without an approved isolated worker.

To run the containerized controller:

```bash
docker compose --project-directory . -f infra/compose/production.yaml up -d --build
```

The controller is bound to loopback by default. Worker nodes are configured separately using `infra/compose/worker.yaml`. Never mount the Docker socket on a CAPSULA controller or expose an unauthenticated worker on the public internet.

For more, see [Deployment](docs/operations/DEPLOYMENT.md), [Cluster operations](docs/operations/CLUSTER.md), [Environment configuration](infra/env/) and [Release checks](tools/release_validate.py).

## Where we are. Where we're going.

**Available in the v0.8 alpha source:** workspaces, mission governance, encrypted artifacts, agent-computer contracts, distributed worker scheduling, file-capable disposable capsules, real Docker execution tests, signed evidence, OIDC tenant APIs and finance-provider integration surfaces.

**Verified:** automated regression and PostgreSQL queue tests; an actual disposable Docker file-processing run on a GitHub runner with output digest and teardown checks; Vultr API account and instance discovery.

**Still to be verified on the live cloud:** the installed public CAPSULA application, independently provisioned Vultr worker VMs, end-to-end Serverless Inference calls, multi-VM containment, and real merchant-provider payment operations. Code presence is not deployment evidence.

The direction is bigger than executing a script. CAPSULA is becoming a computing layer for human and artificial work: agents that have continuity when they need it, temporary machines when they don't, tools they can trust, and results people can own, inspect and use.

**The future of work should feel less like managing software — and more like making things happen.**

---

<sub>CAPSULA · Medina Labs · Alpha v0.8.0 · Apache-2.0 · [Changelog](docs/releases/CHANGELOG.md) · [Source layout](tools/layout.json)</sub>
