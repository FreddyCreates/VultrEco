# CAPSULA · Work Operating System

**Intelligence has a place to work.**  
**Medina Labs · v0.5.0-alpha.1 · Vultr Agent Rush control plane**

CAPSULA gives agents actual workspaces and controlled computer access: a responsive operator interface, encrypted project files, durable memory, agent identities, natural-language plan compilation, reviewed workflows, isolated execution, job and worker registries, content-addressed artifacts, invoices and wallet proposals, and cryptographically signed evidence.

For Vultr Agent Rush, this repository deploys on Vultr:

- Cloud Compute hosts the control plane. `python scripts/provision_vultr.py` creates one Ubuntu VM labeled `capsula-agent-rush` from `VULTR_API_KEY` and `VULTR_INFERENCE_API_KEY`. A second run reuses that VM.
- Serverless Inference is the agent model. An inference token with no other model URL pins `https://api.vultrinference.com/v1/chat/completions` and the chat model `mimo-v2.6-flash`.
- Per-job Docker on that VM runs Python with `--network none`, a read-only root, dropped capabilities, and CPU and memory caps. The sandbox does not receive the Vultr tokens.
- `GET /api/vultr/live` returns the account balance and instance list, with no secrets.

The same process can run on another machine. Missing tokens fail closed. Local tests are not a public URL, a containment recording, or an attestation. See `hackathon/RELEASE_GATE.md`.

The canonical engine repository `ItsNotAILABS/CAPSULA` remains a separate execution-runtime project. This repository (`FreddyCreates/VultrEco`, product CAPSULA) is the user-facing Work OS. The application can exchange contracts with NEXUS, Loom Cluster, POCKET Agent, NOVA Runtime, LiveVault, PARRALAX, Triple-MCP, and Medina Memory, but their external deployments are **not silently assumed connected**.

## Built now

**Release focus:** autonomous mission contracts, delegated capsule trees, a separate opt-in scheduler, code-generation / sandbox loop with retry, and disposable browser screenshot + vision verification. See [RELEASE_SCOPE.md](RELEASE_SCOPE.md) for exact authority boundaries and unmet live deployment gates.


| Area | Product behavior | Proven status |
|---|---|---|
| Command deck | 12 responsive application sections, status/metrics and live data | Local HTTP + API tests |
| Workspaces & files | Create projects; encrypt and version text files; reject traversal; compare expected revisions | Tested |
| Autonomous missions | Authorize once, run bounded cycles, delegate child capsules, pause/cancel, persist goals, signed audit | 277 local tests incl. negative paths; real model/worker must be configured |
| Agent registry | Create, scope, disable agents; explicit capabilities, step ceiling and model identity | Tested |
| Natural-language planning | Model generates strict, validated JSON steps; plan creates a reviewable approval request, never auto-executes | Contract tested; real model requires configured endpoint |
| Workflow engine | Compose runs, require approval for effects, execute bounded steps, seal results, stop on failure | Tested |
| Missions & computers | Leased workers, allowlisted origins, worker dispatch, job history; Docker per-job runner | Loopback worker smoke passes; independent isolation must be verified |
| Models | Operator-pinned OpenAI-compatible provider: local service, self-hosted Ollama-compatible server, or remote HTTPS | Mocked local compatible endpoint tested; no live model claimed |
| Memory & artifacts | AES-256-GCM records, content hashes, revisions, artifact custody | Tested |
| Trust/evidence | Ed25519 signed receipts, Merkle inclusion, domain-separated signatures, offline verifier, signed governance log | Tested locally; **no TEE/hardware attestation** |
| Wallet/finance | Phantom connection in browser; bounded payment proposals and draft invoices | Non-custodial, **no transaction signing/broadcast** |
| Deployment | Dockerfile and socket-free controller Compose; separate worker deployment | Config prepared, not externally deployed |

### Agent self-execution and opt-in scheduler

In the **Autonomous missions** tab, create a goal and choose a model-enabled agent.
Select a strict capability subset plus max cycles, child capsules, steps, token planning
budget, and deadline. **Approvals** must authorize the root mission contract; then
activate. A separate scheduler (or authenticated manual tick) can execute cycles
and scoped delegations without further human interaction, but it cannot gain new
capabilities or authorize financial spending. Child capsules are separate mission
records and run Python/browser code only on actual approved isolated workers.

To start the scheduler as an additional service after setting credentials:

```bash
docker compose -f docker-compose.production.yml -f docker-compose.autonomy.yml up -d --build
```

The scheduler calls the internal control plane, not the Docker daemon. For direct
local testing: `python autonomy_daemon.py` with `CAPSULA_CONTROL_URL` and
`CAPSULA_API_KEY` set. To stop: halt the scheduler and cancel/pause active goals.

### Code and browser verification

The **Challenge** API has model-generated Python proposals, sandbox results,
verified-error retries and approval gating. Browser use is read-only, with a
per-job disposable Playwright container and a separate opt-in vision review
capability. Provision `CAPSULA_MODEL_VISION_MODELS` and a network-enforced browser
egress gateway; no screenshot/vision output is simulated when absent.

### Start CAPSULA on your machine (no Vultr)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export CAPSULA_API_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export CAPSULA_DATA="$PWD/data"
uvicorn app:app --host 127.0.0.1 --port 8080
```

Open http://127.0.0.1:8080, enter the API key, create a workspace, add files, create an agent, compose a workflow, approve it, and inspect receipts. Memory/artifact workflows run on the controller. **Python/browser execution requires an isolated worker**. The default configuration refuses to execute untrusted code on the controller; a broken worker does not cause an unsafe host fallback.

### Connect your own model (optional)

Use any operator-trusted, OpenAI-compatible Chat Completions API. For an Ollama-compatible local service:

```bash
export CAPSULA_MODEL_PROVIDER=self-hosted
export CAPSULA_MODEL_URL=http://127.0.0.1:11434/v1/chat/completions
export CAPSULA_MODEL_ALLOWED_MODELS=your-local-model
# Set CAPSULA_MODEL_API_KEY when using an authenticated endpoint.
```

For private in-network model services, set `CAPSULA_MODEL_URL=http://model-host:11434/v1/chat/completions`, `CAPSULA_MODEL_HOST=model-host`, and `CAPSULA_MODEL_ALLOW_INTERNAL_HTTP=1` **only when the network is operator-controlled**. For remote HTTPS hosts, pin `CAPSULA_MODEL_HOST` to the exact hostname. The server is the only place model endpoints and secrets can be configured. User prompts cannot override the destination, and no mock text is substituted when a provider fails.

Create an agent with the inference capability and an allowed model, enter a goal in **Agents → Natural-language goal**, review the proposed plan in **Approvals**, and explicitly execute it in **Workflows**. Model output is untrusted: the server parses strict JSON, validates each step against the agent's capability set and budget, and requires a separate approval. A model cannot authorize a wallet transfer.

### Run your own workers

1. Deploy the controller (`docker-compose.production.yml`) on your application machine with a private persistent volume. It does **not** mount `/var/run/docker.sock`.
2. Deploy `docker-compose.worker.yml` **on a separate worker VM** with its own Docker daemon; restrict outbound network and access to unrelated hosts. A Docker socket on a worker grants administrative authority over *that worker host*.
3. Configure a strong shared `CAPSULA_WORKER_TOKEN` and an **exact, operator-controlled** `CAPSULA_WORKER_ALLOWED_ENDPOINTS` list. Remote endpoints must use HTTPS; loopback HTTP is for development only.
4. Register workers in **Computers**, maintain leases through authenticated heartbeats, then execute approved Python jobs. Use the signed evidence and containment probe before trusting results.

The browser worker is experimental: build the disposable browser image using `docker build -f browser.Dockerfile -t capsula-browser:local .` on a dedicated worker VM, then deploy `docker-compose.browser.yml` with the **actual** network-level egress gateway/allowlist. A Python allowlist alone is insufficient against DNS rebinding or malicious subrequests. Never share the controller host with browser worker Docker administration.

### Test and verify

```bash
pytest -q
python -m compileall -q .
node --check static/app.js
python smoke_worker.py
python release_validate.py
```

The loopback smoke runs trusted literal Python in an explicitly unsafe test-only worker mode and proves dispatch/results/receipt mechanics, **not** actual VM isolation. No Vultr, AWS, third-party KMS, external witness or on-chain settlement is asserted verified. Use `python verify_evidence.py` and `python verify_governance.py` with a pinned public key for independent record verification.

### Current API groups

- Platform: `/api/health`, `/api/platform`, `/api/providers`, `/api/overview`, `/api/templates`
- Projects: `/api/workspaces`, `/api/project-files`, `/api/project-files/read`, `/api/project-files/revisions`
- Agents: `/api/agents`, `/api/agents/{id}/plan`, `/api/agents/{id}/runs`, `/api/agent-runs/{id}/execute`
- Execution: `/api/missions`, `/api/workers`, `/api/jobs`, `/api/missions/{id}/evidence`
- Memory: `/api/memory`, `/api/artifacts`
- Inference: `/api/inference/complete`
- Governance: `/api/approvals`, `/api/audit`, `/api/security/posture`, `/api/federation/contracts`
- Finance: `/api/invoices`, `/api/finance/intents`, `/api/finance/grants`

**Pre-1.0 disclosure:** Single administrator only (no production identity/tenant separation), no external cryptographic witness or hardware attestation, no integrated paid inference unless configured, no self-running scheduler, and no production financial execution. External services require independently provisioned credentials and security review. Do not expose this alpha directly to the public internet with a weak API key. The Vultr Agent Rush deadline does not change these claims.

See `ARCHITECTURE.md`, `DEPLOYMENT.md`, `PRODUCTION.md`, `OPERATOR_BOUNDARY.md`, `WORKER_SECURITY.md`, and `CHANGELOG.md` for release boundaries.

- Autonomy: `/api/autonomy/goals`, `/api/autonomy/goals/{id}/activate`, `/api/autonomy/goals/{id}/tick`, `/api/autonomy/goals/{id}/children`, `/api/autonomy/scheduler/tick`, `/api/autonomy/playbooks`
- Challenge flows: `/api/challenge/code/propose`, `/api/challenge/code/retry`, `/api/challenge/preflight`
