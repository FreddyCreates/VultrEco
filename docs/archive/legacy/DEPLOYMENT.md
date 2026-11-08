# CAPSULA deployment playbook (pre-1.0)

**No live Vultr deployment has been verified by this release.** Provisioning must use the operator's Vultr account. This describes a controlled lab pilot, not an internet-safe hosted SaaS.

1. Provision separate Vultr control-plane and worker instances, with private ingress and restricted networks.
2. Copy the release archive, verify its SHA-256 manifest and pinned independent release signature if provided by an external signer.
3. Set a strong `CAPSULA_API_KEY`, unique `CAPSULA_WORKER_TOKEN`, `CAPSULA_WORKER_ALLOWED_ENDPOINTS`, and persistent data volume. Never commit secrets.
4. Start controller: `docker compose -f docker-compose.production.yml up --build -d`. This does not mount the Docker socket.
5. Start worker on separately isolated VM with `docker compose -f docker-compose.worker.yml up --build -d` after setting `CAPSULA_WORKER_HOST_RUN_PATH` and `DOCKER_GID`. Docker socket grants administrative authority to the worker VM; do not co-host control plane or unrelated workloads. Its network must be operationally reachable only via the private control plane; never expose port 8081 on the public internet. Require TLS for remote workers.
6. Configure private HTTPS gateway with hardened authentication, rate limits, and access logging. This app still uses a single-admin API token.
7. Register worker via POST `/api/workers` with its exactly configured endpoint, then run authenticated heartbeats every 15–30 seconds to maintain a 45-second lease.
8. Confirm a Python task yields an independently verifiable signed receipt, then run a malicious-task denial test in a disposable VM. Do not use production secrets during the denial test.
9. Connect Vultr Serverless Inference by configuring `VULTR_INFERENCE_URL`, `VULTR_INFERENCE_HOST`, `VULTR_ALLOWED_MODELS`, `VULTR_INFERENCE_API_KEY`. Only valid, approved provider configuration permits inference.
10. For browser sandbox use a separate microVM or hardened disposable VM, externally enforced egress controls, and appropriate kernel sandboxing. The included browser compose file is **experimental**, not an approved public sandbox.
11. Back up `/app/data/capsula.sqlite3` and `/app/data/keys` together to a separately encrypted location. Rotate operational API tokens on schedule. Never publish the private signing key.
12. Confirm test receipt, smoke receipt, release manifest, dependency scan, uptime evidence, and an external network isolation exercise before claiming deployment readiness.

## Production gates

No payment signing or broadcasting, PARRALAX clearing, custody, real wallet spending, third-party attestation, externally witnessed log anchoring, or multi-tenant identity is active. Use the API as a private research alpha only.