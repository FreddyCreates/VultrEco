# CAPSULA Operator Boundary

- **Authority** — single authenticated administrator, in-memory browser key. No multi-user RBAC/SSO; never share the single administrator token with agents or untrusted clients.
- **Agents** — persistent logical identities and explicit capabilities. Model-generated plans are untrusted JSON proposals, bounded by the agent's role, allowed actions and max steps. A separate recorded approval precedes execution.
- **Execution** — Python/browser code executes only via a registered worker with a valid lease or explicitly opted-in local isolated runtime; direct Docker execution on the controller is disabled by default. Worker's successful response is a claim, not attestation.
- **Memory/artifacts** — AES-256-GCM encryption bound to workspace IDs and revisions. Signed custody verifies operator key origin, not the honesty of the host.
- **Inference** — model URL and model allowlist are operator environment variables, not settable by agents. Remote HTTP is rejected; trusted private-network HTTP requires explicit operator pinning and opt-in.
- **Finance** — proposals and invoice drafts exist; user wallet discovery is client-side. No keys/custody, signing, broadcasting, automated payouts or spending authority are enabled.
- **Provider** — deploy on local hardware, private VMs or a chosen cloud. Vultr is optional; the core app does not depend on a Vultr account.


RAH grants allow recursive execution only within the owner's exact existing VM pool and aggregate reservations. No model proposal creates host allocation authority. Agent continuity, curiosity and skill drafts are reference data, not credentials or grants. A verified improvement promotes exact project revisions; rollback refuses to overwrite later edits. Ordinary authentication remains a single-operator bearer key; organizational lanes do not establish multi-tenant access control.
