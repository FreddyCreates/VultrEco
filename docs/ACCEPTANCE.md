# Acceptance: separate evidence gates

CAPSULA 0.6.0-alpha.1 integrates the complete Work OS source, dedicated agent computers, bounded RAH, agent continuity and clean improvement capsules. Source, local process, VM/container, model and Vultr deployment verification are separate claims.

## Reproduce source checks

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
python3 smoke_worker.py
python3 release_validate.py
node --check static/app.js
python3 scripts/verify_release_manifest.py
cd runtimes/dot
python3 scripts/validate.py
```

The root suite includes real baseline/candidate Python execution **only in a named trusted test fixture**, plus API, cryptography, continuity, scope, replay, budget, promotion and rollback contracts. That fixture never becomes the production executor. The ordinary smoke script explicitly enables unsafe subprocess mode for literal test code and must not be used as containment evidence. Production improvement trials reject that mode.

The Dot suite covers leases, queues, recovery, checkpoints, browser action contracts, recursive work trees, provisioning replay, safe imports, dependency handoff hashes and change accounting. It uses a hypervisor fixture for source tests. Historical kernel/VM/browser tests from the prior release remain under `runtimes/dot/receipts/historical-v0.4` and do not validate newly changed bridge code.

## Real clean worker acceptance

`scripts/verify_clean_worker.py` uses the actual CAPSULA application and actual HTTP worker transport. It has no fixture executor or controller code fallback. It tests a rejected candidate, a distinguishing passing candidate, atomic promotion, rollback, automatic learning/procedure draft creation and signed audit verification. The containment case checks UID, controller/worker credential environment absence, inability to write to root, public-network denial and the live cgroup memory/CPU/PID limits. The optional bootstrap inspection confirms actual Docker command arguments and that no job containers remain active.

`scripts/build_worker_probe.py` prepares an isolated Linux VM image for this test using operator-supplied QEMU/BusyBox, Docker static binaries and worker Python dependencies. It includes no controller signing key, controller API key or provider cache. A short-lived worker-service token stays outside the per-job containers. Docker daemon administration belongs to that dedicated worker VM, not the application host. The generated image contains that disposable token and is intentionally **not** committed or distributed.

The local probe uses QEMU TCG CPU emulation and an actual Linux kernel, Docker daemon and per-job containers. It is not a Vultr deployment or hardware KVM test. Passing limited containment cases does not constitute an independent security audit or proof against every kernel/runtime exploit.

## Kernel regression discovered by real execution

The previous image booted Linux and ran processes but did not enable BPF syscalls/cgroup BPF. Docker's OCI runtime rejected its device-control setup. The profile now requires `CONFIG_BPF_SYSCALL=y`, `CONFIG_CGROUP_BPF=y` and `CONFIG_BPF_JIT=y`; the source build script checks these gates before compiling. A kernel that merely boots does not establish that a container runtime can enforce its controls. Failed bootstrap/runtime attempts remain recorded separately from any successful acceptance receipt.

## Still separate live gates

- Configure and run the privileged Dot host on a real KVM/libvirt machine; verify its provisioning, cloud-init, systemd, firewall and signed-in Codex/Gemini tasks.
- Exercise the CAPSULA-to-Dot connection, actual multi-VM recursive RAH and artifact transfers on that host. Source fixtures alone do not establish those deployments.
- For the Vultr challenge, run the central controller, isolated execution and Serverless Inference on Vultr; retain the real URL and provider traces.
- Verify production browser egress, tenant identity/RBAC, external key management/witnessing and any future wallet settlement separately. They are not silently enabled by this release.

The current machine-readable evidence is in `test-receipt.json`, `receipts/` and the root release hash manifest. Read their exact statuses and environments before making a claim.

## Recorded result for this release

`receipts/clean-worker.json` passed actual HTTP-to-worker execution in an ext4-root QEMU Linux guest. Two trials retained the negative candidate and verified the improvement, then promoted and rolled back. The containment job observed UID 65534, `memory.max=201326592`, `cpu.max=50000 100000`, `pids.max=64`, no controller/worker token variables, a read-only root and denied public networking. Docker calls and no remaining active job containers were checked. The controller ran outside that VM. This remains local CPU-emulated VM/container evidence, not Vultr, provider inference or hardware attestation.
