# Agent computer milestone

This release implements the source path for: **assign work → checkpoint → execute → verify → interrupt → restore → resume → export files**.

## Status

A real local recovery exercise runs ordinary Python worker processes and real project tests. It does not run an LLM or a VM. Its receipt explicitly identifies that boundary. That v0.3 receipt establishes local recovery only. In v0.4, a custom Linux kernel compiled, two QEMU guests completed reboot/persistence/rollback checks, and Chromium rendered the dashboard; see `receipts/historical-v0.4/kernel-build.json`, `receipts/historical-v0.4/qemu-acceptance.json` and `receipts/historical-v0.4/browser-acceptance.json`. Subscription inference and production KVM/libvirt acceptance remain unverified.

Run the executable exercise:

```bash
python3 scripts/exercise_recovery.py --out /absolute/path/new-recovery-run
```

It creates a passing project, snapshots it, terminates a worker after an incorrect write, observes failing tests, reloads its stored mission, restores the checkpoint, resumes a worker and observes passing tests. It preserves artifact hashes and an execution receipt.

## Real guest acceptance

After Linux KVM host setup and subscription sign-in, stop the controller but leave both VMs running:

```bash
sudo python3 scripts/verify_live.py --config config.json \
  --agents CHATGPT_AGENT_ID GEMINI_AGENT_ID --recovery \
  --out receipts/live-recovery.json
```

This gate requires real provider completion, a pre-task checkpoint and file acceptance evidence. With `--recovery`, it also interrupts a task while its explicit acceptance command is running, restores the workspace, then requires a second provider task and artifact to pass. No fixture backend is accepted.

## Persistent mission context

Use **Computer → Mission** to save an objective and owner notes. Future tasks receive that context and bounded recent outcome metadata. The runtime persists it in the owner database; it is not hidden model reasoning, an encrypted memory product or a provider login cache. Saving a mission does not independently schedule work or change a running task's authority.

## Acceptance checks

Choose a project test/build command and required artifact in the task form, or use the API:

```json
{
  "prompt": "Implement the project and satisfy the checks",
  "timeout": 600,
  "acceptance": {
    "commands": [["python3", "-m", "unittest", "-v"]],
    "files": [{"path": "calculator.py", "contains": "return a + b"}]
  }
}
```

Commands execute as argument arrays inside the guest, after the provider process finishes. They run within the task deadline. A failure prevents completion. Host processing matches the reported check list against the owner's requested checks. These are operational checks, not independent attestation against a compromised guest, nor a proof that model-authored tests cover every requirement.

Without configured checks, provider completion is reported without a claim of verified project acceptance.

## Checkpoints

Every work task checkpoints the workspace before provider execution. Manual create/list/restore operations are in **Computer → Checkpoints**. Restore first saves an undo checkpoint and then swaps a staged, hash-verified workspace into place; an interrupted swap has a recovery journal. Active tasks block manual workspace mutation.

Checkpoints cover regular workspace files, including hidden project files. They exclude separate provider credential directories. They preserve owner execution bits and empty directories. Symlinks and workspaces over 128 MiB are rejected. They are guest-local plaintext content-addressed backups, subject to VM disk capacity; this release does not claim encrypted checkpoints or automatic garbage collection. Restore does not reverse external effects.

## Computer and owner takeover

Terminal access uses the per-agent pinned SSH connection. The browser panel invokes a real optional Playwright Chromium installation inside the VM. It supports navigation, page text and screenshots; the guest helper additionally supports selectors for clicking and filling. This is a browser surface, not a full remote desktop or graphical OS shell.

The takeover control requests task cancellation. Wait for terminal cancellation before editing or using the computer interactively. It does not instantly suspend a running model or roll back its actions.

Browser installation inside the VM requires `python3-venv`, an exact Playwright version, Chromium and its Linux shared-library dependencies. Run:

```bash
DOT_PLAYWRIGHT_VERSION=1.62.0 bash install_guest_browser.sh
```

Copy the included script into the guest first. Dependencies can be baked into the base image by the host operator using Playwright's documented Linux dependency installation. Missing packages, browser binaries or shared libraries return errors; no synthetic screenshots or pages are substituted.

## Existing guest upgrades

A host upgrade does not rewrite a running guest. Stop its tasks, gracefully shut it down, and use:

```bash
sudo python3 scripts/upgrade_guest.py --config config.json --agent AGENT_ID
```

The upgrader verifies the assigned disk/UUID and refuses active tasks or a running domain. It retains a disk backup and uploads guest protocol 0.3 sources with libguestfs. The updated guest still needs a real boot and health check. Restore the retained disk while stopped if the upgrade fails.
