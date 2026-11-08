# CAPSULA — Live demo runbook (record actual Vultr VM)

## Prerequisites

- Control-plane VM and separate dedicated worker VM are running on Vultr; worker is reached over a private authenticated network.
- Real Vultr Serverless Inference key and available model configured. Never show or embed secrets on video.
- Per-job Docker sandbox is enabled on the worker VM; `CAPSULA_WORKER_DEV_ALLOW_UNISOLATED` is **unset**.
- Public HTTPS CAPSULA URL works from an unauthenticated viewer's browser (with authorized login for interactive operations).
- Test results include worker job lifecycle and verifiable signed receipts.

## Five-minute filmed narrative

1. Show CAPSULA dashboard, create a mission and name the authorization boundary. Explain how the controller uses Vultr.
2. Show model-generated bounded Python code using Vultr Serverless Inference; display model request/response safely without secrets.
3. Dispatch to the separately deployed worker, show job start, isolation constraints and real stdout, not an invented result.
4. Open the receipt, signed event log and artifact view. Download evidence and run the offline verifier with the pinned public key.
5. **Containment moment:** attempt a disallowed network egress or read-only root write inside the disposable job; show a reproducible failure, worker teardown and surviving controller. Never point this at a third-party service. Use `scripts/containment_probe.py` to get deterministic probe code.
6. Show memory continuity and the current state of Wallet/Pay, explicitly identifying proposals as non-spending.
7. Close with real-world use cases and an honest limitations slide.

## Proof capture checklist

- Vultr VM instance identity and deployment diagram; scrub credentials, public SSH endpoints and private addresses.
- Docker sandbox invocation with `--network none`, `--read-only`, resource limits and dropped capabilities.
- Execution result and corresponding signed evidence bundle.
- Verification output using separately pinned Ed25519 public key.
- Screenshot or log of a denied sandbox operation and of subsequent worker health.
- Public URL visible in browser address bar.
- One successful real Vultr inference call (model name, response, non-secret request ID).

## Safety constraints

The probe must run **inside the per-job Docker sandbox only**, not on the controller or worker host. A code-level denial is not proof of network-layer isolation by itself. Sandbox container logs and host-side verification should agree.


## Expanded autonomous computing demonstration (v0.5)

1. Create an agent with an operator-pinned model, `inference`, `artifact`, `memory`, and `python` capabilities.
2. Create a root autonomous mission in the Autonomous missions screen, set a deadline, max cycles, child slots and token allowance.
3. Show that execution is denied before the signed-off contract is approved; approve and activate.
4. Run a cycle; show its child-capsule tree, encrypted artifact, signed run receipt and auditable budget.
5. Demonstrate an attempted capability escalation is rejected. Pause or cancel the root and show descendant execution cannot proceed.
6. Show a separate disposable worker container handling model-created Python; run the actual read-only-root and network-denial containment probe.
7. Optionally demonstrate read-only browser screenshots and visual review using a pinned vision model on the isolated browser worker VM.
8. Show live Vultr VM and Vultr Serverless Inference traces if entering Blast Radius Zero. Do not substitute local smoke tests for those live proofs.
