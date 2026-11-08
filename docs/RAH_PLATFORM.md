# RAH is an agent and enterprise work platform

RAH means **Recursive Agentic Hierarchy**. The durable unit is an authorized work capsule; agents are replaceable executors. CAPSULA brings the existing project/files/model/workflow/proof application together with persistent computers, recursive mission grants, agent continuity, experiment proposals and clean improvement trials.

## The requested operating loop

1. Give an agent its own project, durable objective/notes, computer and bounded authority.
2. Let it perform useful software, research, analysis, operations, QA or file work. A mission may run independent branches and refine child work inside the owner's original limits.
3. Capture actual outcomes and evidence. Retain failures. Use them to propose small experiments and reusable procedures.
4. Freeze a baseline, exact writable files, old behavior and a distinguishing desired behavior. Execute candidate code in clean per-job workers without model/provider/controller credentials.
5. Compare expected answers outside the candidate process. Require preserved old behavior plus a measured new result. A polished response or passing flag is insufficient.
6. Promote only the verified revisions, keep rollback, and advertise only the unchanged promoted procedure to future work. Store continuity so the next session can resume without inventing prior state.

`learning.py` implements durable per-agent objectives, working notes, recent outcomes, curiosity proposals and skill drafts. Completed workflows automatically draft a procedure under `skills/proposals`; failed/denied work proposes a bounded diagnostic experiment. Dedicated VM tasks also keep guest-local observations automatically and feed CAPSULA continuity when their computer is inspected/refreshed. The console polls the selected computer only while an authenticated session is open. No permanent background work is promised by a closed browser or chat session.

`improvement_lab.py` freezes encrypted project snapshots and acceptance cases. `platform_routes.isolated_trial` selects an exact allowlisted, leased Python worker, rejects unsafe development mode, verifies the returned digest and creates signed trial records. Expected outputs remain in the controller. A candidate cannot inspect them by reading the generated worker program. The controller never imports, evals or subprocesses candidate code. Tests have a separately named trusted executor fixture; it is not a production fallback.

## Mission authority

| Transition | Authority | Result |
|---|---|---|
| Natural-language plan | Agent's configured model, no grant | Reviewable proposal; no effect |
| RAH mission grant | Authenticated owner | Signed objective/contract plus explicit computer pool and limits |
| Root/child execution | Dot host's current bounded lease | Work in the assigned VM only |
| Branch growth | Existing granted pool, maximum depth/count, remaining reservations/deadline | Accepted or denied child request, durably recorded |
| Dependency handoff | Exact owner-selected dependency/path | Hash-checked text copy with target checkpoint and charged bytes |
| Improvement grant | Owner-frozen source, cases and write paths | Bounded clean trials; no arbitrary host command authority |
| Procedure promotion | Exact passing candidate and unchanged source revisions | New audited revisions and optional active procedure |
| Revocation/rollback | Owner | Stop future granted work / restore prior content without overwriting later edits |

Provisioning and RAH admission use durable replay keys. Ambiguous transport can be retried with the identical grant; a conflicting body is rejected. A branch cannot allocate new VMs, mint a larger budget, invent provider access, copy host secrets or extend its deadline. The Dot host retains queue and graph state independently of a browser tab. External report text and imported files are data, not authority.

## Personal and enterprise lanes

An individual agent keeps private continuity and a dedicated computer. Enterprise projects group files, agents, missions, procedures and evidence under an explicit workspace/organization lane. The owner can reuse verified procedures within that workspace while agent objectives remain distinct.

This version is still a **single-operator alpha**. The organization label is not an identity provider, tenant boundary, RBAC system or proof of regulatory compliance. Do not expose it as an unrestricted multi-user SaaS. Independent remote worker attestation, external KMS/witnessing and full enterprise identity remain separate work; the UI does not fabricate them.

## Self-improvement boundaries

Curiosity is implemented as useful, bounded experiment proposals derived from owner objectives and observed gaps. It does not mean the platform invents unbounded purposes or receives extra spending/network permissions. Skill drafts are not automatically active instructions. A frozen acceptance set measures those cases and may be overfit; it is not independent evidence of general intelligence improvement.

The assistant collaborating on this repository can use its procedures, capsules, tests and durable handoff, and maintain a relevant personal skill. It cannot modify its underlying model weights, platform instructions or remain attached and executing after a session ends. `AGENTS.md` makes the reusable work practice explicit for future project sessions.

## Actual API surfaces

- `GET/POST /api/agents/{id}/continuity`, `GET /learning`, `POST /curiosity`.
- `POST /api/agents/{id}/computer`, `POST /computer/bind`, `GET /computer`, `POST /computer/sync`, `POST /computer/tasks`.
- `POST/GET /api/rah/missions`, `GET /api/rah/missions/{id}`, `POST /cancel`.
- `POST/GET /api/improvements`, `GET /{id}`, `POST /{id}/candidate`, `/evaluate`, `/promote`, `/rollback`, `/revoke`, `/recover`.
- `GET/POST /api/workspaces/{workspace}/lane`.

Current source/clean-worker evidence is described in [ACCEPTANCE.md](ACCEPTANCE.md). Prior compiled-kernel and QEMU/browser evidence is retained in `runtimes/dot/receipts/historical-v0.4`; changed bridge code needs its own current-host verification.
