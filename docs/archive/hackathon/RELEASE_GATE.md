# CAPSULA v0.8.0-alpha.1 — Vultr Agent Rush acceptance

CAPSULA is a broad agent computing platform. Vultr Cloud Compute, fleet APIs
and Serverless Inference are the intended central challenge infrastructure.

| Requirement | Status | Evidence / next acceptance |
|---|---|---|
| Complete, versioned GitHub source | PASS | v0.7 on main; release manifest and CI |
| Full GitHub regression tests | PASS | 334/334 on prior v0.7 CI; updated deployment PR is subject to recheck |
| PostgreSQL distributed jobs/fencing | PASS (CI) | PostgreSQL 16 integration, no duplicate completion in 40-job/4-client benchmark |
| Multi-host Vultr provisioning | IMPLEMENTED, not executed | Provider price validation, idempotent labels, budget approval, SSH bootstrap |
| Vultr Cloud API connection | PASS | HTTP 200 for account + instances through GitHub Actions |
| Existing Vultr control VM | DISCOVERED | `capsula-control` active in DFW; not an app health check |
| Application installed on Vultr VM | NOT VERIFIED | Pinned SSH workflow with required credentials; inspect `/api/health` |
| Live dedicated worker VMs | NOT VERIFIED | Enroll at least two distinct VM workers and pin identities |
| Real containment: isolation/secrets/limits/teardown | NOT VERIFIED | Run multi-VM probe and record refusals/worker cleanup |
| Vultr Serverless Inference response | NOT VERIFIED | Add separate inference credential and record actual response/trace |
| Public HTTPS app and enterprise login | NOT VERIFIED | Domain/host key, Caddy TLS, public end-to-end login and scoped mission |
| Recorded demonstration | NOT PROVIDED | Show code + browser task, real output, denial and receipts |
| LabLab final entry | NOT SUBMITTED | Verify public URL, repo, video, project summary and submission |
| External memory/agent federation | PARTIAL | Internal adapters; NEXUS, Loom and others require integration validation |

**Do not confuse a signed controller record with trustworthy host isolation or
a database latency benchmark with actual multi-VM work.** Publish measured
evidence at each security and deployment gate.

## v0.8 additional release acceptance

- User-file → disposable worker → verified output download: implemented and tested
  against a deterministic worker response; live Vultr container proof pending.
- Worker enforces bounded mounts, cleanup verification, file path restrictions,
  and artifact digests: covered by alpha test suite, VM acceptance pending.
- Enterprise finance: tenant OIDC, Stripe Checkout requests and exact HMAC
  webhook reconciliation: PostgreSQL tests, merchant credentials pending.
- No payouts, bank debits, custody or exchange APIs are represented as live.
- No additional paid Vultr hosts are automatically created by this release.
