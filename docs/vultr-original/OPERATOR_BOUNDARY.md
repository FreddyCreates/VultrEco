# Operator boundaries

- Never authorize untrusted agents to administer the control-plane VM or Docker daemon.
- Single-admin API key is not user identity, tenancy or role-based access. Keep the alpha private.
- Worker tokens must be unique and rotated. Registration requires a preconfigured exact endpoint; nonloopback workers require TLS.
- Local process resource limits and Docker restrictions are layered defenses, not a formal proof of VM containment.
- Browser worker with `--no-sandbox` requires an external microVM/VM boundary; DNS allowlist by itself does not prevent rebinding or SSRF. Use an egress firewall/proxy.
- Finance intents and proposal grants are not authority to spend. Every real transaction requires a future approved, user-signed transaction and settlement reconciliation.
- Receipts prove possession of the operator key and integrity of recorded data, not independent truth of actions or host measurements.
- Keep a separately pinned public signing key. A key bundled with untrusted evidence does not identify a trusted signer.
- Protect backups of encrypted state and signing keys separately; do not publish credentials or private artifacts.
- Review licenses and dependencies and retain attribution for reused upstream code before hackathon submission.