# CAPSULA deployment — Vultr Agent Rush infrastructure

**Primary challenge topology:** Vultr Cloud Compute controller in DFW,
separate Vultr worker and dedicated-agent VMs, PostgreSQL queue, approved
Vultr Serverless Inference, signed receipts and optional public HTTPS edge.
The repository's existing `capsula-control` VM was detected as active via
the Vultr API, **not yet validated as an installed CAPSULA application**.

**Step 1 — Use existing control VM:** Configure GitHub environment
`capsula-deploy`, SSH private-key secret `CAPSULA_DEPLOY_SSH_KEY`,
verified `CAPSULA_SSH_KNOWN_HOSTS`, `CAPSULA_ADMIN_API_KEY`, and variable
`CAPSULA_DEPLOY_SSH_USER`. Optionally point `CAPSULA_PUBLIC_FQDN` to the VM
before enabling Caddy. Run the manual workflow
`vultr-existing-deploy.yml`. It pins the specific Vultr VM and exact git commit
before verifying CAPSULA's health. It does not provision additional paid VMs.

**Step 2 — Capacity:** Use the separate `vultr-fleet-deploy.yml` workflow,
with monthly budget cap, existing SSH key and explicit paid approval, to
provision dedicated worker/agent hosts. Deploy the worker runtime and
`cluster_runner.py` there with scoped tokens and secure private PostgreSQL
connectivity. Never send cloud, model or vault keys to job containers.

**Step 3 — Inference:** Add `VULTR_INFERENCE_API_KEY` to GitHub deployment
secrets, then verify an actual authorized Serverless Inference request from
the deployed controller. Do not claim it connected solely from an env setting.

**Step 4 — Certification:** Run
`scripts/benchmark_multi_vm.py` against at least two independent HTTPS
worker hosts, with direct identity and containment checks; verify public
HTTPS, login, model response and record a real demo.

See [the full release gate](hackathon/RELEASE_GATE.md) and
[cluster operations](docs/CLUSTER_OPERATIONS.md).

---

# Alternative self-hosted deployment

## 1. Create a controller

Provision a Linux machine with Python 3.11+ or Docker Engine and Compose. Keep its admin port private. The production container binds to `127.0.0.1:8080` and **does not** mount the Docker socket.

```bash
cp .env.example .env
# Replace API key, set model config if desired, never commit .env
python -c 'import secrets;print(secrets.token_urlsafe(48))'
docker compose -f docker-compose.production.yml up -d --build
curl http://127.0.0.1:8080/api/health
```

Set a TLS reverse proxy, authentication boundary, rate limiting and encrypted backup plan before any public exposure. Only a single-admin authentication model exists at this stage.

## 2. Choose your model (optional)

Local non-Docker development:
`CAPSULA_MODEL_URL=http://127.0.0.1:11434/v1/chat/completions` and `CAPSULA_MODEL_ALLOWED_MODELS=<installed-model>`.

Containerized private-network model:
`CAPSULA_MODEL_URL=http://model:11434/v1/chat/completions`, `CAPSULA_MODEL_HOST=model`, `CAPSULA_MODEL_ALLOW_INTERNAL_HTTP=1` (requires operator-controlled private network).

External HTTPS model:
`CAPSULA_MODEL_URL=https://<trusted-host>/v1/chat/completions`, `CAPSULA_MODEL_HOST=<trusted-host>`, `CAPSULA_MODEL_API_KEY=<secret>`.

No inference is attempted when unconfigured. Vendor-specific adaptors, including Vultr, can be mounted later using the same OpenAI-compatible model contract.

## 3. Isolated execution worker (separate host)

Follow `WORKER_SECURITY.md` and `docker-compose.worker.yml` on a disposable isolated worker VM. Install Docker there, provide a private task mount and strong worker token. Never connect unrelated production hosts to a worker Docker socket. Set the controller's exact worker allowlist and register the worker in the UI; the worker lease is 45 seconds and needs periodic authenticated heartbeat renewal.

## 4. Operator proof + validation

```bash
pytest -q
python smoke_worker.py
python release_validate.py
```

The smoke is **not** an isolation proof: it explicitly uses a development-only, trusted-code execution path. To establish containment, run `scripts/containment_probe.py` **inside the real disposable worker** and retain actual network/namespace evidence from the deployment. External attestation is not integrated.

## 5. Backups, custody and recovery

Back up `/app/data/capsula.sqlite3` and `/app/data/keys` together, with encrypted offline backups and restrictive file permissions. Encryption keys are local and currently lack automated rotation/recovery. Losing the AES-GCM key makes encrypted records unrecoverable. Keep `CAPSULA_API_KEY` and worker tokens out of the repository.


## Dedicated agent computers and RAH

Host `runtimes/dot` on a separate Linux KVM/libvirt machine following its deployment instructions. Create its owner token and configuration on that host. Point `CAPSULA_DOT_URL` and `CAPSULA_DOT_TOKEN` at its private management transport. The Dot service is loopback-bound; use a same-port SSH tunnel (`8787` to `8787`) or an operator-controlled HTTPS proxy that forwards the expected loopback Host header. Never put this token into JavaScript, a worker, or a provider prompt.

In Agent evolution, choose an agent, create or inspect its dedicated computer, sign in using the official CLI inside that VM, save its objective and sync project files. ChatGPT/Gemini authentication is interactive in the VM; no API-key substitution is performed. In RAH missions, select distinct provisioned computers, define the objective/dependencies, optional file handoffs, child pool and limits, then grant the mission once.

API sync is limited to visible, noncredential text files totaling 96 KiB; use SCP for larger projects. Import creates an undo checkpoint and refuses active work. Handoffs have the same size boundary and additionally reserve from the target branch's change budget.

## Clean improvement workers

Deploy the Python worker on a dedicated worker VM with per-job Docker configured. Register and heartbeat its allowlisted endpoint as documented above. Agent evolution can freeze a small text project (10 KB baseline / 12 KB candidate), entrypoint, exact writable paths, regression cases and distinguishing new cases. Every case runs in a new network-none, read-only, unprivileged container; expected outputs remain on the controller. The lab rejects direct controller execution and the unsafe loopback smoke mode. Owner-authored acceptance cases measure those cases, not a general intelligence benchmark.

Use `scripts/verify_clean_worker.py --endpoint YOUR_PRIVATE_WORKER --token-file /secure/worker-token --out /private/new-acceptance` for actual worker acceptance. `scripts/build_worker_probe.py` can prepare a disposable local Linux test VM with operator-supplied static Docker binaries and QEMU/BusyBox. This is a test recipe, not automatic paid cloud provisioning or a production Docker distribution. Keep its generated image/token outside Git.

New controller images copy the continuity, RAH and improvement modules plus the pure Dot contract validators. They do not gain the Dot host's privileges or a Docker socket. The Vultr profile still requires actual Vultr hosting, network containment and Serverless Inference evidence before submission.

For an independently running local VM acceptance probe, after building the private worker initramfs, run:

```bash
python3 scripts/verify_vm_worker.py --kernel /path/bzImage --initrd /private/worker.cpio.gz --toolchain /path/extracted-tools --token-file /private/disposable-worker-token --out /private/new-vm-proof
```

The command creates a new disk, binds the worker port to host loopback, uses actual QEMU/Docker and shuts the guest down after acceptance. Only its sanitized receipt is suitable for publication; its controller data, raw disk, generated initramfs and disposable token stay private.

## 6. Autonomous scheduler, providers and browser workers

Operator authorizes mission contracts in the web UI. The scheduler is a separate
opt-in process: `docker compose -f docker-compose.production.yml -f docker-compose.autonomy.yml up -d --build`.
It invokes the API with the controller key on the private Compose network, not a host shell.
Run only after an approved inference endpoint has been configured; no model is silently provisioned.

For browser agents, build the one-shot image on an isolated worker machine:
`docker build -f browser.Dockerfile -t capsula-browser:local .`. Provide a private
Docker-network whose outbound requests are explicitly filtered by a real gateway
allowlisting selected HTTPS hostnames and resolved public IPs. Then configure
`CAPSULA_BROWSER_NETWORK`, `CAPSULA_BROWSER_ALLOWLIST`, and
`CAPSULA_BROWSER_EGRESS_ENFORCED=1` (the flag is an operator assertion, **not** attestation).
Run `docker compose -f docker-compose.browser.yml up -d --build` on that worker VM.
The worker service starts a fresh container per browser task; the control plane does not.
A separate `CAPSULA_MODEL_VISION_MODELS` allowlist controls screenshot review.

For the Vultr Agent Rush submission, deploy the control plane on Vultr VM, the
workers on separate disposable Vultr VMs, and wire Vultr Serverless Inference
using `CAPSULA_MODEL_PROVIDER`, `CAPSULA_MODEL_URL`, and model allowlisting.
Collect real logs and containment probe outputs. Do not call local loopback tests
a production isolation pass.

## v0.8 execution and finance service

Deploy the CAPSULA controller separately from worker VMs. Rebuild both
`Dockerfile.production` and `worker.Dockerfile`: they now include
`capsule_api.py`, `capsule_runtime.py` and the finance adapters. Run
`python scripts/migrate_cluster.py` against your private PostgreSQL
database before activating enterprise routes. The worker Docker daemon
remains exclusively on dedicated workers, with per-job `--rm` and explicit
post-run destruction checks.

For hosted payments, add `CAPSULA_STRIPE_SECRET_KEY`,
`CAPSULA_STRIPE_WEBHOOK_SECRET` and
`CAPSULA_FINANCE_PUBLIC_ORIGIN` only to the controller's secure environment.
Configure the provider webhook to POST
`/api/v1/finance/stripe/webhook` over HTTPS. Never send merchant credentials
to capsules, PostgreSQL task payloads or browser clients. The current Vultr
VM installation and a live payment-provider webhook remain unverified.
