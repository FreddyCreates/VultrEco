# CAPSULA worker security boundary — v0.3.0-alpha.1

## Implemented

- Worker service with separate bearer token, no Docker-socket requirement, worker lifecycle registration and 45-second leases.
- Per-worker endpoint must match an operator-configured allowlist; no arbitrary user endpoint execution.
- Remote output includes a digest checked by the control plane; final receipt signed by the controller.
- Container manifests specify dropped capabilities, non-root user, no-new-privileges, read-only root, pids/CPU/memory limits.
- Python worker runs in network-none container with process CPU and file limits. THIS DOES NOT REPLACE hardened VM isolation.
- Browser module validates HTTPS, resolves global IPs, requires host allowlist, and blocks cross-origin requests at Playwright routing.

## Critical conditions for production

- Browser uses Chromium without built-in sandbox. Do not expose to untrusted browsing until running inside an independently isolated microVM or hardened VM with host-level network policy and approved seccomp/AppArmor.
- Browser DNS validation is vulnerable to post-check rebinding absent a network-level egress proxy. Do not treat application routing as the security boundary.
- Worker identity is a bearer secret; register worker identities via mutually authenticated transport in a future release.
- Worker-reported output and hash are not independent proof of the worker state or VM integrity.
- API remains single-admin; do not place behind public multi-tenant login.
- Controller Docker socket in legacy compose is a development-only mechanism; use the separate worker deployment for real integrations.
- Wallet accounts are discovered in browser only; no backend signing, spending or chain broadcasts are implemented.

## Per-job Python isolation mode

Default worker execution now **fails closed** unless `CAPSULA_WORKER_HOST_RUN_PATH` and a Docker worker daemon are provisioned on a **separate dedicated worker VM**. Each code mission launches an ephemeral Docker container with no network, dropped capabilities, read-only filesystem, unprivileged UID, and bounded resources. The long-lived worker service itself can access the worker VM Docker daemon: that is host-admin authority and must be physically separated from the control plane and from all unrelated tenants. A hardened VM boundary, Docker daemon access controls, and external evidence are still required. The direct subprocess path is only accessible when the explicit `CAPSULA_WORKER_DEV_ALLOW_UNISOLATED=1` flag is set for a trusted loopback smoke test. That flag must never be used with arbitrary input or in deployment.
