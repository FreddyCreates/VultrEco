# RAH improvement lab

RAH means **Recursive Agentic Hierarchy**. Its flagship direction is a platform for an individual agent and an enterprise work tree to learn from completed work, propose experiments, verify improvements, and preserve useful procedures. This release implements a concrete workspace improvement loop alongside the existing bounded VM mission scheduler. It does not claim autonomous model-weight improvement or a live deployed RAH fleet.

## What works

- Each guest job records a durable learning observation containing status, an evidence hash and whether explicit acceptance checks passed. Raw prompts, responses and provider credentials are not copied into observations.
- Work-mode prompts invite useful procedure proposals under `skills/proposals/NAME/SKILL.md`, within the existing task's change/time grant. No extra model call or background job is launched merely to learn.
- An owner creates an improvement capsule: objective, exact writable paths, workspace lane, namespace, expiry, attempts, byte budget and two frozen Python verifiers.
- A baseline and candidate snapshot are created outside the live workspace. Frozen verifiers run in fresh processes with a scratch HOME and a minimal environment. Provider environment variables are not inherited.
- The baseline and candidate must both pass regressions. A distinguishing check must fail on the baseline and pass on the candidate. Failed trials are preserved; reject-everything and pass-everything verifiers cannot satisfy this gate.
- Promotion requires the exact verified candidate and unchanged live baseline. It saves an undo checkpoint, checks installed bytes and restores after a write failure. A persisted journal recovers an interrupted promotion on the next mutating lab operation.
- Rollback refuses to overwrite work changed after promotion. Expired/revoked capsules cannot execute. Every trial consumes an attempt before execution.
- Future jobs receive references only to exact, promoted `skills/active/*/SKILL.md` files whose current bytes match the promoted artifact. Proposed or subsequently edited skills are excluded.
- The authenticated owner dashboard exposes the lab from an agent's Computer details: create, edit, inspect, evaluate, promote, revoke and rollback. Mutation events enter the host receipt chain.

## Authority and isolation

This is an **owner-operated, single-owner tool**. The trusted owner supplies verifier code through the local CLI or authenticated dashboard. A verifier executes arbitrary Python, so run untrusted candidate code in a disposable VM with no private credentials or valuable mounts. Each VM remains subject to the existing host and guest limits/firewall.

The lab's directories, frozen hashes and namespace fields are not an adversarial security boundary. Code running as the same operating-system user could access other same-user files. In particular, setting a scratch HOME is not protection against reading an explicitly addressed login cache. Do not use a signed-in persistent agent VM as a hostile-code evaluation sandbox. Clean verifier VM routing, cross-VM candidate transfer, root-owned verifier state and independent remote attestation remain future integration work. Existing guest SSH transport is implemented; its real-host lab flow has not been exercised here.

`scope=agent` and `scope=enterprise` preserve distinct use cases and a namespace in durable capsules. Supply separate state/work roots per organization. This release does not provide tenant accounts, tenant isolation, fleet billing or enterprise access control.

Frozen check code and hashes establish reproducibility within a trusted operator environment. They do not establish hidden-test secrecy from a malicious same-user candidate, impartial verifier authorship, test sufficiency, cryptographic guest attestation or proof of general intelligence gains. The distinguishing check is an owner-authored acceptance test, not an externally held research benchmark.

## Use in a VM

Create a JSON spec outside the candidate workspace. `regression` and `holdout` contain Python source, each receiving the target snapshot directory as `sys.argv[1]`:

```json
{
  "objective": "Support negative inputs without breaking positive inputs",
  "scope": "agent",
  "tenant": "private",
  "allowed_paths": ["calculator.py"],
  "regression": "import pathlib,sys,runpy\nm=runpy.run_path(str(pathlib.Path(sys.argv[1])/'calculator.py'))\nassert m['double'](2)==4\n",
  "holdout": "import pathlib,sys,runpy\nm=runpy.run_path(str(pathlib.Path(sys.argv[1])/'calculator.py'))\nassert m['double'](-3)==-6\n",
  "seconds": 30,
  "lease_seconds": 3600,
  "attempts": 3,
  "max_changed_bytes": 1048576
}
```

From an installed source checkout inside the evaluation VM:

```bash
python3 -m dot.improvement create --state /home/dot/lab --workspace /home/dot/project --spec /home/dot/spec.json
```

Edit only the granted files under `/home/dot/lab/CAPSULE_ID/candidate/`, or use the dashboard candidate editor. The live project is unchanged until promotion. Then:

```bash
python3 -m dot.improvement evaluate --state /home/dot/lab --workspace /home/dot/project --id CAPSULE_ID
python3 -m dot.improvement promote --state /home/dot/lab --workspace /home/dot/project --id CAPSULE_ID
python3 -m dot.improvement rollback --state /home/dot/lab --workspace /home/dot/project --id CAPSULE_ID
```

Dashboard evaluations allow 30 seconds; the terminal supports a larger explicitly bounded budget. Mutations share a lab lock. Guest RPC also shares the normal workspace lock with jobs; do not separately run CLI mutations concurrently with other workspace writers.

Keep source workspaces small and free of hidden state, Git directories, secrets, symlinks and special files. Copies are limited to 128 MiB / 10,000 files. Use a clean export instead of a repository containing `.git` or provider caches.

## Actual use on this release

`receipts/historical-v0.4/self-improvement.json` records a real application of this mechanism to `dot/computer.py`. The original browser action validator rejected a bounded wait action. A candidate added selector validation, a 1–8000 ms bound, and real Playwright `wait_for` dispatch. Baseline regressions passed, the baseline failed the new contract check, and the candidate passed both checks before promotion. The source change was authored by the assistant; no provider inference or real browser was executed in that particular experiment. Separately, the resulting browser controls passed an actual Chromium guest probe, and the improvement lifecycle passed 26 tests in each of two real Linux guests, including persistence and rollback after reboot.

`scripts/exercise_improvement.py` reproduces that source experiment against the original v0.3 browser baseline. It intentionally refuses to rerun on the already updated file. General lifecycle, rollback, restart, tamper, scope, budget and HTTP integration tests run via `scripts/validate.py` against temporary workspaces. Hypervisor transport in HTTP tests is a fixture; verifiers themselves execute as actual Python processes.

## Next flagship gates

| Capability | Current evidence | Remaining gate |
|---|---|---|
| Outcome learning and procedure proposals | Source integration tested | Real provider-driven task in a signed-in VM |
| Baseline/candidate improvement | Actual source patch promoted | Broader independent holdouts and real workload measurements |
| Recovery | Failure injection plus two actual guests rebooted, persisted improvements and rolled back | Production host power-loss acceptance |
| Separate-worker RAH tree | Existing scheduler tested | Live multi-VM subscription execution |
| Clean evaluation VM | Credential-free, network-free QEMU guest tests executed | Automated production routing and cross-VM candidate transfer |
| Cross-session skill reuse | Installed reusable workflow | Relevant future sessions must load/use it |
| Enterprise platform | Namespace and workspace lane metadata | Identity, access control, tenant isolation and audit deployment |

The assistant can improve tools, procedures, project memory and evaluation coverage. This does not modify its underlying model or keep it running after a session. New skills are reusable instructions, not new model weights.
