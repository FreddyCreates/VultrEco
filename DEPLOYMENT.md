# CAPSULA self-hosted deployment (no required cloud)

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
