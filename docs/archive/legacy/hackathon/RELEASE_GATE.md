# CAPSULA Alpha submission readiness gate

| Gate | Evidence | Status |
| --- | --- | --- |
| Local tests | `python -m pytest -q`: 160 passed | PASS (local) |
| Static release verification | `python release_validate.py` | PASS (local) |
| Genuine worker loopback | `python smoke_worker.py` | Re-run on desired operator VM |
| Per-job Docker isolation on Vultr | worker-VM security logs, denied network/root writes | NOT VERIFIED |
| Vultr Serverless Inference | real model call & request trace | NOT VERIFIED |
| Public Vultr deployment | valid HTTPS URL & external browser test | NOT VERIFIED |
| Signed evidence and artifact verification | evidence download, pinned public-key verification | Needs live run |
| Browser agent isolation | egress firewall, DNS/rebinding and origin policy test | NOT VERIFIED |
| Loom Cluster / Pocket Agent integration | external E2E test | NOT CONNECTED |
| Wallet money movement | real user-authorized signed settlement | NOT CONNECTED (proposals only) |
| GitHub source publish | public repo contains build | BLOCKED: GitHub App not installed on FreddyCreates |
| Submission video / slide presentation | links | NOT READY |
| Hackathon official submit | LabLab confirmation | NOT SUBMITTED |

Release stage: **0.3.0-alpha.1**, not 1.0. A signed receipt is not a hardware attestation. The platform can only claim containment when it is independently tested at the worker VM boundary.

## GitHub access resolution

Current GitHub App installation covers `ItsNotAILABS` only. The repository `FreddyCreates/VultrEco` is under the separate `FreddyCreates` personal account. Install or authorize the same GitHub App for `FreddyCreates`, grant access to `VultrEco` and Contents write permission, then retry upload. Do not create another repository as a workaround without approval.