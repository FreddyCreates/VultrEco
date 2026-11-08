# CAPSULA architecture (local alpha)

User browser → single-admin FastAPI mission control → NEXUS-compatible admission/policy → worker scheduler (SQLite leases) → isolated worker transport → result/provenance → controller-signed mission receipt → encrypted memory/artifact store.

Planes:
- **User/team:** single-admin only, no true tenant isolation.
- **Federation:** NEXUS local task/handoff contracts; external NEXUS and Loom Cluster unconnected.
- **Execution:** separate worker API and deployment manifests; Python process under worker container resource limits. Browser alpha only, network protections incomplete.
- **Model:** Vultr inference configurable with pinned HTTPS hostname and allowlisted models; untested remotely.
- **Memory:** SQLite index, AES-GCM sealed records and content-addressed artifacts, local keys.
- **Proof:** Ed25519 signed domain-separated mission and governance records, Merkle inclusion paths, offline pinned-key verifiers. No witness or hardware attestation.
- **Finance:** browser wallet discovery, invoice drafts, budget proposals and unsigned payment intents. No keys, no custody, no chain broadcast.

Canonical external technology is preserved: NEXUS, Loom Cluster, CAPSULA runtime, POCKET Agent, NOVA Runtime, LiveVault, Medina Memory, Triple-MCP, PARRALAX. The app never claims an unavailable external service is active.