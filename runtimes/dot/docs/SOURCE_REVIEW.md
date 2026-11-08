# Existing-work review and integration

Reviewed current connected GitHub source during this build. No remote repository was modified.

| Existing component | Inspected source | Applied boundary |
|---|---|---|
| CAPSULA | README, `capsula/ecosystem.py`, `capsula/portable.py`, `capsules/schema/capsule-contract.v1.json` | Bounded task scope/budgets; sealed NOVASVAUL imports; artifact/hash/handoff lineage |
| POCKET Agent | README, `src/pocket_agent/family_protocol.py` | Durable execution, explicit authority, request/agent correlation, operational receipts without private reasoning |
| MatDaemon | README, `matdaemon/ecosystem.py` | Guest-local bounded compute; does not own identity or replace VM isolation |
| Organism Bots | README | Repeatable workflow acceptance needs outputs and evidence; steps alone do not prove success |

Source locations:

- https://github.com/ItsNotAILABS/CAPSULA
- https://github.com/ItsNotAILABS/pocket-agent
- https://github.com/ItsNotAILABS/MatDaemon
- https://github.com/ItsNotAILABS/organism-bots-mcp-server

Vendored CAPSULA files retain their upstream MIT license in `dot/vendor/CAPSULA-LICENSE.txt`.

| Vendored contract | Upstream Git blob SHA |
|---|---|
| `capsula_ecosystem.py` | `829b0758fe776ef3a47466bd94ffcfb1f49e7b09` |
| `capsula_portable.py` | `9b315e94d3201a79afb4ad274522578f84d05d2f` |
| `capsule-contract.v1.json` | `0cbc78d76aa1908796d93a93a5e09d7e4d9ef356` |

The POCKET receipt mapping is implemented locally; the POCKET harness is not silently substituted or claimed installed. NEXUS federation shape does not authenticate a remote NEXUS service: the owner-only HTTP API remains the authority for this runtime.

Optional MatDaemon use inside a guest can follow the inspected project's SDK/MCP installation instructions. It is not a required dependency of the subscription runtime, and there is no synthetic numerical worker presented as MatDaemon.

CAPSULA contract import is an authenticated `POST /api/agents/{id}/capsule` operation. The controller validates the source schema, deny-default sealed permissions, declared record count and upstream content hash, then transports the unchanged sealed bundle into that VM. Imported sealed state never triggers execution.

External provider references consulted:

- https://learn.chatgpt.com/docs/auth — ChatGPT subscription authentication; headless device code flow.
- https://learn.chatgpt.com/docs/cli/reference — Codex structured execution and sandbox flags.
- https://geminicli.com/docs/get-started/authentication/ — Google subscription authentication and cached credentials.
- https://geminicli.com/docs/cli/headless/ — structured headless output.
- https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/code_assist/oauth2.ts — manual authentication when browser launch is suppressed.
- https://geminicli.com/docs/reference/configuration/ — approval and sandbox modes.
- https://docs.kernel.org/kbuild/kbuild.html — Linux build controls.
- https://libguestfs.org/virt-customize.1.html — offline image customization.
- https://www.libvirt.org/manpages/virsh.html — guest lifecycle operations.
