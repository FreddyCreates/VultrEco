# v0.4.0 — RAH improvement lab

- Added bounded improvement capsules with exact file grants, frozen regression and distinguishing checks, separate baseline/candidate snapshots, expiry, attempt/time/change budgets and preserved failed trials.
- Added byte-bound promotion, undo checkpoints, interruption recovery, stale workspace denial and rollback.
- Added automatic hash-only task observations, procedure proposal prompts and exact promoted-skill references in later jobs.
- Added authenticated per-agent lab controls and a dashboard panel for both agent and enterprise project lanes.
- Used the lab to verify and promote bounded asynchronous browser wait support in the actual project source.
- Added persistent project instructions and a reusable personal workflow for future relevant sessions.
- Compiled Linux 6.6.162-itsnotai-dot, booted two actual QEMU TCG VMs twice each, and passed 26 improvement tests per VM plus reboot persistence and rollback.
- Verified actual Chromium desktop/mobile dashboard rendering inside a clean guest. Source, exact config, minimal initramfs and receipts are included; full upstream kernel source is provided separately.
- Kept hardware KVM/libvirt, provider subscription inference, Debian package installation and permanent production deployment unverified. Directory snapshots are not a security sandbox; enterprise lanes are not multi-tenant isolation.

# Changes

## 0.3.0

- Add persistent owner mission context and bounded recent outcome records.
- Automatically checkpoint workspace files before work, with content-addressed storage, hash checks, undo checkpoints and journaled restore.
- Run explicit owner acceptance commands and artifact checks after provider completion; require matching evidence at the host.
- Add bounded multi-agent mission graphs, dependency tracking and parent cancellation.
- Add opt-in recursive child/grandchild proposals through a polled outbox, limited to an approved pool, depth, child count, shared reservations and absolute deadline.
- Add dashboard mission, checkpoints, browser, takeover and project-check controls.
- Add optional real Playwright Chromium guest control and a stopped-guest source upgrader retaining a disk backup.
- Execute a local interruption, rejection, restore and resume exercise with real Python project tests.
- Extend the real-host acceptance script with checkpoint evidence and optional interruption/recovery checks.
- Kernel compilation, VM boot, graphical browser execution and subscription inference remain unverified here.

## 0.2.0

- Persist request keys and request digests in the same transaction as task insertion, so repeated requests return the same job across restarts. Reject conflicting reuse.
- Persist cancellation before SSH; reconcile task state and retry a unit stop after connectivity returns.
- Reject guest result identity mismatches and malformed timestamps, statuses, artifacts and hashes. Preserve all host-owned authority fields.
- Recover interrupted provisioning records through explicit disk/UUID inspection of an existing VM.
- Reject stale health writes after a concurrent VM power action using agent generations.
- Serialize receipt-chain writers with a SQLite immediate transaction, including separate controller/CLI runtime instances.
- Use descriptor-relative, no-follow reads and content verification for workspace ZIP exports.
- Produce operational receipts for queued cancellation and lease-expiration denial.
- Add 14 reliability and boundary tests; 40 total tests pass.

Live VM/kernel boot and subscription inference remain unverified in the build environment. These changes do not change the release's PARTIAL status.
