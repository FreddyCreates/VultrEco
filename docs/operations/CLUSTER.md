# CAPSULA v0.7 cluster operations

## Shared data plane

A PostgreSQL 16+ database is the durable queue authority. All controllers
connect to the **same** DB. Workers claim tasks using `FOR UPDATE SKIP LOCKED`,
but **the worker record is locked first**, serializing per-worker capacity
admission. Every claim increments a monotonically growing epoch and rotates
a 256-bit random fence secret. Renew/finish are compare-and-swap operations on
tenant + job + worker + epoch + token + unexpired lease.

When a lease expires, the scheduler requeues (or dead-letters) the job. A
stale worker's subsequent result is rejected even if it still has the old
token. **This does not kill its process.** Deploy VM-side watchdog termination,
command idempotency and infrastructure fencing before using jobs with
irreversible external side effects. Keep payment, deletion and external writes
approval-gated.

## Identity and tenancy

- TLS 1.2+ at ingress. Do not expose PostgreSQL or worker Docker sockets.
- OIDC RS256, operator-pinned HTTPS issuer/JWKS and audience.
- Tenant and role claims are signed; tenant is never trusted from a URL alone.
- `viewer` may read tenant status, `operator` may submit jobs,
  `admin` may enroll/drain workers and reconcile leases.
- Worker credentials are random per-worker bearer tokens, stored only as a
  digest in PostgreSQL, scoped by the worker's tenant.
- Rotating a worker credential means revoking/re-enrolling that identity;
  use a secrets manager to distribute the new token securely.
- Legacy CAPSULA admin APIs are **disabled** when
  `CAPSULA_ENTERPRISE_MODE=1`. This is a migration guard, not full enterprise
  RBAC for the old UI. No tenant data is copied from SQLite automatically.

## Worker deployment

A host with a separate Docker daemon runs the existing `worker_runtime.py`
as an internal service with `CAPSULA_WORKER_TOKEN` and the per-job Docker
execution mode. The new `cluster_runner.py` connects to PostgreSQL and calls
that worker on a pinned loopback HTTPS/or loopback HTTP origin.

```bash
export CAPSULA_CLUSTER_DATABASE_URL='postgresql://...sslmode=verify-full'
export CAPSULA_CLUSTER_WORKER_ID='wrk_...'
export CAPSULA_CLUSTER_WORKER_TOKEN='per-host-secret'
export CAPSULA_EXECUTOR_URL='http://127.0.0.1:8081'
export CAPSULA_EXECUTOR_TOKEN='separate-local-executor-secret'
python cluster_runner.py
```

Register a worker using the tenant-admin API, then inject the returned worker
token on **that** host only. Never put worker secrets, Vultr tokens, project
encryption keys or model credentials into a job capsule. The runner verifies
`/health` reports `per-job-docker-or-deny`, checks the result digest and
returns fenced results. It never executes arbitrary Python in its own process.

## Recovery and operations

`POST /api/v1/cluster/{tenant}/reconcile` transitions expired leases to
queued/dead, preserving the epoch. It also emits a provider-independent audit
event that states remote termination was *not* proven. Configure draining
before host shutdown and stop the runner cleanly before revoking worker tokens.
Monitor queued/leased/dead by tenant and compare them with host heartbeat.
Keep PostgreSQL WAL, encrypted backups, and measured restore drills.

Failure drills required before production: worker power loss mid-job; late
result arriving after reassignment; database failover during claim; exhausted
quotas; KVM isolation and guest-to-host escape probes; network egress leak;
identity and tenant confusion; revoked signing keys; full disk; object-store
unavailability; and one failing inference provider.

## Capacity and multi-host provisioner

The provider planner enforces a **maximum of eight hosts per operation**,
requires an explicit OS image, previously registered SSH key, monthly budget
ceiling and the actual Vultr plan price. An existing label is reused only if
region and plan match. Cloud-init has no platform secrets. This is not yet
autoscaling; the planner is an operator-invoked provisioning surface.

## Current evidence

Local application source and GitHub CI exercise the contracts. The independent
PostgreSQL benchmark measures queue throughput, not VM or container isolation.
Live Vultr bootstrap, external TLS, multi-VM load and verified provider inference
must have their own signed receipts before publication.

## Existing Vultr control VM deployment

Use `.github/workflows/vultr-existing-deploy.yml` under the protected
`capsula-deploy` GitHub environment. It reads `VULTR_API_KEY` solely to
select the exact active `capsula-control` VM in `dfw`, then uses a pinned
SSH private key and verified `known_hosts` entry to install the exact GitHub
commit. It requires a strong `CAPSULA_ADMIN_API_KEY`, explicit SSH user, and
operator approval. Inference credentials are optional and remain absent if no
separate Vultr Serverless Inference key is configured.

The controller's Docker socket remains unmounted. Without a configured
`CAPSULA_PUBLIC_FQDN` and matching DNS, the service stays private at VM
loopback. With a configured domain, the Caddy edge service acquires HTTPS and
the workflow verifies public `/api/health`. A healthy API is **not** worker
isolation certification. Deploy worker VMs separately, with their own daemon,
network policy, TLS and cluster enrollment.
