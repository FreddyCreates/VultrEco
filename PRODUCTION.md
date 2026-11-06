# Production state — CAPSULA 0.3.0-alpha.1

**Classification: LOCAL ALPHA (not deployed, not certified).**

The source provides a tested local control plane and lease-based worker transport with signed evidence. A loopback process execution has been observed end-to-end, with a verified mission receipt. The socket-free controller image is authored but has not been built or deployed here. Docker container isolation, Chromium browser isolation, Vultr network access, external inference, and real wallet settlement have not been verified here.

Completed gates: Python syntax, API regression, policy denial, signed evidence, encrypted memory/artifact integrity, NEXUS local contract validation, wallet proposal rejection, governance audit tampering and loopback worker execution.

Open gates: external NEXUS/LOOM/POCKET service health probes, live Vultr credentials, real worker VM network attestation, browser egress certification, external key management, multi-user RBAC, independent audit log witness, production payment authority, observability and recovery testing, and an external red-team test.

Operator must not treat a local signature as hardware attestation; key material currently lives on a local filesystem. A compromise of the controller compromises its signing key unless external key isolation is added.