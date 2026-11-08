> CAPSULA integration update: this runtime adds idempotent RAH admission, safe project import and explicit dependency file handoffs. Prior v0.4 kernel/guest/browser evidence is retained under `receipts/historical-v0.4`; it is historical evidence, not a live test of this updated host bridge. Run current source validation and real-host acceptance separately. Compiled binaries are supplied in the earlier downloadable release; this repository carries source, configuration and reproduction scripts.

# ITSNotAI Dot · Medina Capability Kernel · v0.4

A single-owner agent operating runtime. Each agent has a persistent **Linux KVM virtual machine**, its own writable disk, separate SSH identity, provider login cache and workspace. An authenticated dashboard manages agents and work. ChatGPT subscription work runs through the official Codex CLI; Google AI Pro/Ultra subscription work runs through the official Gemini CLI.

**Release status: PARTIAL production acceptance.** The custom Linux 6.6.162 kernel compiled and booted in two actual QEMU TCG guests on separate disks. Each passed 26 improvement tests, promoted a change, rebooted, verified persistence and rolled back. The authenticated dashboard also passed actual Chrome desktop/mobile checks inside a third clean guest. These are real CPU-emulated VMs; hardware KVM/libvirt, production Ubuntu provisioning and subscription inference remain unverified. Test fixtures remain confined to source tests; the guest acceptance additionally exercises actual Linux boots and processes.

New in v0.4: **[RAH improvement lab](docs/RAH_IMPROVEMENT.md)** for private-agent and enterprise project lanes, automatic task observations, frozen baseline/candidate checks, durable skill proposals, verified promotion and rollback. The lab was used on an actual source change in this release; it does not claim live VM or provider validation.

See [docs/CHANGELOG.md](docs/CHANGELOG.md) for the v0.3 checkpoint, verification, continuity and bounded delegation improvements.

## What is implemented

- Actual libvirt/virt-install VM provisioning with a verified, standalone qcow2 base image.
- Dedicated guest disk, guest SSH host key and owner management key per agent.
- Medina Capability Kernel mission leases: signed request/agent scope, expiration, execution mode and resource limits.
- Bounded autonomous tool execution inside the guest, as a non-root user.
- ChatGPT device-code login and Gemini manual Google login directly in the guest terminal.
- Persistent SQLite queue, one active job per agent, parallel jobs across separate VMs, restart reconciliation and no automatic repeat of ambiguous dispatches.
- Systemd guest job units with memory/process/time limits and cgroup cancellation.
- Root-owned guest firewall restricting inbound management to the host and blocking outbound private/metadata networks.
- Artifact hashes, workspace ZIP export, cancellation and POCKET-shaped operational receipts.
- CAPSULA `nexus.task.v1` validation and NOVASVAUL `capsule.contract.v1` sealed import, using vendored current upstream helpers and schema.
- Pre-task workspace checkpoints, restore-with-undo, and crash recovery journals.
- Owner-specified acceptance commands and artifact checks, separate from provider completion.
- Persistent mission objectives, notes and bounded recent outcome metadata.
- Bounded team graphs with opt-in recursive child requests to an approved pool of separate agent VMs.
- Optional real Chromium navigation, inspection and screenshot controls inside the guest.
- A custom Linux kernel profile, source-archive verification, Debian package build and qcow2 installation scripts.
- Local validation and separate real-host acceptance scripts.

## Start here

Read **[DEPLOYMENT.md](DEPLOYMENT.md)** for host preparation, verified source/image inputs, custom Linux kernel compilation, image creation, subscription sign-in and acceptance checks.

Run source checks:

```bash
python3 scripts/validate.py
```

Run on a configured Linux KVM host:

```bash
sudo python3 -m dot doctor --config config.json
sudo python3 -m dot serve --config config.json
```

Open `http://127.0.0.1:8787`, enter the token from `/var/lib/itsnotai-dot/owner.token`, create an agent and sign in using its **Computer** panel instructions.

## Two kernels, clear responsibilities

**Linux kernel:** the actual operating-system kernel in each guest. `kernel/dot.config` defines a hardened x86-64 virtio/cgroups/seccomp/AppArmor/Landlock profile. The build scripts produce a real `bzImage` and Debian kernel package when supplied with verified upstream Linux source and a build host. The earlier v0.4 downloadable artifact contains the compiled headless image and minimal acceptance initramfs; this integrated source checkout carries the exact configuration, source metadata and reproduction scripts. A Debian kernel package was not built. See [kernel/VM reproduction](docs/KERNEL_VM_PROOF.md).

**Medina Capability Kernel:** `dot/kernel.py` is the user-space authority layer. It grants a bounded mission, validates capsule contracts, checks scope before dispatch and creates operational receipts. It is not represented as a replacement for the Linux kernel.

## Existing ecosystem

The build was informed by current CAPSULA, POCKET Agent, MatDaemon and Organism Bots source. CAPSULA task and sealed-transfer contracts are integrated. POCKET execution receipts are mapped. MatDaemon is an optional guest-local compute tool; it is not preinstalled, invoked, or claimed live by this release. Full POCKET/NEXUS identity federation is not implemented. Recursive delegation uses an explicitly approved pool of existing VMs; automatic infrastructure allocation is not implemented. See [docs/SOURCE_REVIEW.md](docs/SOURCE_REVIEW.md).

Subscriptions retain the account's provider quotas and workspace permissions. Creating more VMs does not multiply account entitlements. This is an owner-operated runtime, not a resale gateway or a multi-user SaaS service.

## Project recovery milestone

See [docs/MILESTONE.md](docs/MILESTONE.md) for the executed local recovery exercise, real-host recovery gate, checkpoint operations, acceptance checks, browser installation and existing-guest upgrades. See [docs/BOUNDED_DELEGATION.md](docs/BOUNDED_DELEGATION.md) for recursive authority and resource limits.
