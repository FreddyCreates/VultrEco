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
