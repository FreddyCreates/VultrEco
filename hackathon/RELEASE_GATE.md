# CAPSULA 0.6.0-alpha.1 | submission gates, November 8, 2026

This platform is broader than procurement or finance. Engineering, browser use,
research, documents, data analysis, support, sales, recruiting, finance and
procurement are optional capability playbooks. The application runs provider
independently; the hackathon submission requires real Vultr deployment evidence.

| Gate | Status | Reproducible proof |
| --- | --- | --- |
| Full application source | PASS | Integrated v0.6 source; see the release manifest and merged commit |
| Complete local Python tests | PASS (local) | `pytest -q`: 317 passed |
| Syntax + version + release gate | PASS (local) | `compileall`, `node --check`, `release_validate.py` |
| Signed worker loopback | PASS (non-isolated smoke) | `python smoke_worker.py`: result 42, signed receipt |
| Operator-authorized recursive capsules | PASS (API tests) | mission contract, scoped child authority, pause/cancel, scheduler |
| Model-to-code, policy, retry | PASS (contract tests) | Challenge API, bounded worker path; real model requires configuration |
| Disposable browser and vision | PASS (contract tests) | worker image, egress preconditions, screenshot vision adapter |
| Actual local container isolation in separate Linux VM | PASS (QEMU TCG) | `receipts/clean-worker.json`; not live Vultr acceptance |
| Live Vultr worker containment | NOT VERIFIED | Retain the probe on the deployed worker VM |
| Actual browser network egress gateway | NOT VERIFIED | Run private-IP, DNS rebinding, subresource escape tests |
| Live Vultr Serverless Inference | NOT VERIFIED | Configuration, trace and a real model response needed |
| Public HTTPS Vultr application | NOT VERIFIED | Public URL and independent login/use test needed |
| Real recorded demo with containment moment | NOT PROVIDED | Video link + actual worker logs needed |
| External Loom / Pocket Agent / NOVA / LiveVault | NOT VERIFIED | These remain integration contracts, not connected executions |
| Payment execution / enterprise multi-tenant SSO | NOT IMPLEMENTED | No spend/signing or enterprise RBAC claims |
| LabLab final submission | NOT SUBMITTED | Confirmation screenshot/link required |

Do not represent local tests as deployment, live containment, external attestations,
or verified market/financial activity. A model asserting success is not evidence.
