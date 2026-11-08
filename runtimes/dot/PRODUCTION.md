# Verification and release state

Version: **0.4.0**. Overall: **PARTIAL**. Source implementation exists and local tests pass. The package is not a claim of a fully deployed VM fleet.

| Area | State | Evidence |
|---|---|---|
| RAH improvement loop | Executed on actual source locally | Frozen baseline/candidate checks promoted bounded browser-wait support; receipt included |
| Learning observations and skill references | Source-tested | Real local guest-task process wrote hash-only observation; only exact promoted procedures advertised |
| Improvement owner controls | HTTP flow tested | Authenticated create/edit/evaluate/promote/rollback with actual local verifiers; transport fixture |
| Enterprise lane | Metadata implemented | Separate namespace recorded; no multi-tenant identity or isolation claim |
| Workspace recovery | Executed locally | Real worker interrupted, bad output rejected, checkpoint restored and project tests passed |
| Mission continuity | Source-tested | Objective, owner notes and recent operational outcomes persist in SQLite |
| Bounded recursive delegation | Source-tested | Approved pool, unique VM reservation, depth/budget denial, replay and parent cancellation |
| Browser control | Verified in actual guest | Navigate, fill, click, bounded wait, read and screenshot using real Chrome for Testing |
| Owner HTTP control plane | Locally tested | Auth/origin/path rejection tests |
| Persistent task lifecycle | Locally tested | Queue/cancel/reconnect/restart/ambiguous dispatch tests |
| Retry/cancel recovery | Locally tested | Concurrent request replay, restart persistence and cancellation after SSH loss |
| Guest result boundary | Locally tested | Wrong-job outcomes and authority-field injection rejected |
| Guest subprocess execution | Locally tested with provider fixtures | Real subprocess created a file; hash and ZIP content verified |
| Mission signature/scope | Locally tested | Mutation, wrong-agent and expiration denial tests |
| CAPSULA sealed transfer | Locally tested | Upstream contract/hash helpers plus schema validation |
| QEMU Linux guest boots | Verified | Two unique VMs/disks; four boots; 26 tests per VM, promotion/reboot persistence/rollback |
| Production libvirt/KVM provisioning | Implemented; unverified | Hardware KVM and production Ubuntu/cloud-init acceptance remain |
| Custom Linux kernel | Compiled and booted | 6.6.162-itsnotai-dot bzImage; source SHA, exact config, build and boot receipts |
| Debian kernel package/image upgrade | Unverified | Image-only build; no Debian package or Ubuntu disk installation claim |
| ChatGPT/Gemini subscription inference | Implemented adapters; unverified | Requires owner sign-in on real guests |
| Guest firewall | Root-owned rule installation implemented | Live adversarial reachability testing still required |
| Dashboard browser rendering | Desktop/mobile verified | Actual authenticated controller in Chrome guest; no JS errors or mobile overflow; truthful unavailable host |
| MatDaemon | Inspected; optional | No installed/live compute integration claim |

See `receipts/source-validation.json` for exact executed checks and `scripts/verify_live.py` for real-host acceptance. Passing source tests does not promote VM/kernel/provider entries to LIVE.

The terminal task status `completed` means the official CLI reported a completed turn and a usable response, with artifacts and change-budget checks. Configured owner acceptance commands and file checks must also pass before completion. With no configured checks, no project-acceptance claim is made. These checks do not establish adversarial guest attestation or prove that the chosen tests are sufficient.

No external deployment, paid VM allocation, source-repository push or subscription login was performed from this build workspace.
