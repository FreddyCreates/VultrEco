# CAPSULA 0.4.0-alpha.1 — Readiness and remaining work

**Current:** provider-neutral application with working project, agent, planning, run, approval, memory, artifact and evidence APIs, tested locally. It is **not production-certified**.

**Verified locally:** Python compilation, unit/integration adversarial tests, import and release validation, JavaScript parser, loopback worker process with a real Python output and signed evidence. It is the integration path, not proof of isolation. Browser Chromium visual rendering is restricted by the current automated environment, so screenshots are not offered as UI certification.

**Explicit external gaps:** no live production worker/VM containment attestation; no integrated multi-user identity; no running scheduler/RAH autonomous recursion; no proven actual Loom Cluster scheduling, Pocket Agent federation, LiveVault external key management, PARRALAX settlement; no real wallet signing or bank payment; no live model or cloud runtime deployment proof; no independent security audit.

**Go/no-go:** Never call this v1.0 until sandbox network controls, key isolation, multi-tenant access, attestation/external witness, load tests, recovery, and external API/vendor behavior have been verified. A public hackathon deployment may be labelled *alpha with real contained execution* only after validating the actual worker host's policy and capture evidence.


### v0.5 preproduction boundaries

- Root mission contract plus bounded delegation may run autonomous cycles via a
  separately opted-in scheduler. It does **not** grant production self-modification.
- Multi-tenant RBAC, external witness, managed secrets/KMS and remote SSO are not
  implemented. Payment proposals cannot sign or broadcast transactions.
- For the Vultr challenge, per-job worker isolation, live inference, public demo
  and recorded containment moment require evidence from actual infrastructure.
- Use `RELEASE_SCOPE.md` as the operator declaration of verified vs proposed lanes.
