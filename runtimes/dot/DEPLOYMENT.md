# Linux VM deployment

This package contains the runtime, source checks and a custom Linux kernel build workflow. Complete these steps on an **x86-64 Ubuntu 24.04 host with KVM**, physical or explicitly supporting nested virtualization. A normal managed container is insufficient. The dashboard is loopback-only; remote access uses an SSH tunnel.

## 1. Prepare the host

```bash
sudo bash scripts/install_host.sh
```

Verify `virsh net-info default` and `virsh net-dumpxml default`. The default configuration expects subnet `192.168.122.0/24`, gateway `192.168.122.1`. If your network differs, change the generated config before provisioning; the firewall and SSH access restriction use this gateway. Run the controller on the same VM host.

Reserve at least 4 GB guest RAM, 2 vCPU and 32 GB disk per agent, plus host overhead. The configured allocation limits are reservations, not physical-capacity detection; set them below available host resources.

## 2. Obtain and verify inputs

Download an official Ubuntu 24.04 amd64 **qcow2 cloud image**, an official Node Linux x64 `.tar.xz` release (Node 22 or newer), and an upstream stable Linux source `.tar.xz` archive. Verify publisher checksums/signatures before using them. The scripts require the exact verified SHA-256 values and refuse a mismatch. They do not invent trusted hashes.

Official source locations:

- https://cloud-images.ubuntu.com/noble/current/
- https://nodejs.org/dist/
- https://www.kernel.org/

Use a maintained stable Linux version compatible with the supplied configuration. The profile is merged against that source tree; missing required symbols cause the build to fail. Select and retain exact tool/source versions for your release.

## 3. Compile your Linux guest kernel

```bash
python3 scripts/build_kernel.py \
  --archive /absolute/path/linux-source.tar.xz \
  --sha256 YOUR_VERIFIED_LINUX_SOURCE_SHA256 \
  --out /absolute/path/dot-kernel-build \
  --jobs 4
```

Outputs include `arch/x86/boot/bzImage`, the final `.config`, Debian image/module packages and `kernel-build-receipt.json`. The script runs `make bindeb-pkg`. A successful compile receipt has `boot_verified: false`; only a real VM boot can establish that.

The profile supports virtio disk/network/console, ext4, namespaces, cgroups, nftables, seccomp, AppArmor and Landlock. It uses a deterministic build user/host/timestamp; bitwise reproducibility additionally requires retaining the exact compiler, tools and source inputs.

## 4. Create a base image with Node

```bash
sudo python3 scripts/prepare_base.py \
  --base /absolute/path/ubuntu-noble.qcow2 \
  --base-sha256 YOUR_VERIFIED_UBUNTU_IMAGE_SHA256 \
  --node-archive /absolute/path/node-linux-x64.tar.xz \
  --node-sha256 YOUR_VERIFIED_NODE_ARCHIVE_SHA256 \
  --out /var/lib/libvirt/images/dot-node-base.qcow2
```

This works on a new copy. It installs the verified Node distribution using libguestfs. First-boot cloud-init later installs exact Codex/Gemini CLI releases. Provider credentials are not baked into the base image.

## 5. Install your compiled kernel into a fresh qcow2

Read the Node image SHA-256 from `dot-node-base.receipt.json` and use it here:

```bash
sudo python3 scripts/install_kernel_image.py \
  --base /var/lib/libvirt/images/dot-node-base.qcow2 \
  --base-sha256 SHA256_FROM_NODE_IMAGE_RECEIPT \
  --kernel-dir /absolute/path/dot-kernel-build \
  --out /var/lib/libvirt/images/dot-kernel-base.qcow2
sudo chmod 0444 /var/lib/libvirt/images/dot-kernel-base.qcow2
```

The installer uses the Ubuntu GRUB menu name to select the compiled release. This selection must be checked on your actual image; the live gate requires `uname -r` to match the image receipt. Never replace a base image after agents use it as a backing file.

## 6. Generate exact-version configuration

```bash
python3 scripts/configure.py \
  --image-receipt /var/lib/libvirt/images/dot-kernel-base.receipt.json
```

Without explicit CLI versions, this resolves each current npm release on your host and writes the **exact** version to `config.json`. To choose tested releases, pass `--codex-version X.Y.Z --gemini-version X.Y.Z`. The configuration is validated and existing config files are not overwritten.

```bash
sudo python3 -m dot doctor --config config.json
sudo python3 -m dot serve --config config.json
```

Doctor checks the host toolchain, KVM access, libvirt connection and base-image existence. Provisioning additionally verifies the image SHA-256 and standalone qcow2 format.

## 7. Create and sign in to agents

Open `http://127.0.0.1:8787`. Read the owner token locally:

```bash
sudo cat /var/lib/itsnotai-dot/owner.token
```

Create one ChatGPT agent and one Gemini agent. Initial package installation may take several minutes. Readiness requires the installed CLIs, root-owned firewall marker and, for the custom image, the configured kernel release.

For each agent, use the command in its **Computer** panel:

```bash
sudo python3 -m dot login --config config.json --agent AGENT_ID
```

ChatGPT runs `codex login --device-auth`. Complete the official sign-in link/code on your own browser. Device login must be allowed by the account/workspace. The CLI enforces ChatGPT login mode; there is no automatic API-key fallback.

Gemini runs `NO_BROWSER=true gemini` over an interactive SSH terminal. Use **Sign in with Google** and complete the manual browser/code flow. Use the Google account with your Google AI Pro/Ultra subscription. Google Workspace or organization accounts may require their own project/license configuration.

Credentials stay in each guest. A detected cache is only an indication of saved credentials, not proof of entitlement or working inference. Logs never automatically collect interactive login sessions.

## 8. Verify real operation

Stop the control-plane service before the acceptance gate so it does not schedule other work concurrently. Leave the VMs running. The live gate submits a real task to each official CLI and verifies a generated artifact:

```bash
sudo python3 scripts/verify_live.py \
  --config config.json \
  --agents CHATGPT_AGENT_ID GEMINI_AGENT_ID \
  --out receipts/live-acceptance.json
```

It checks distinct domain UUIDs, non-root guest execution, expected kernel release, completed inference and artifact content. It does not substitute fixtures. The receipt separately reports that adversarial network-isolation testing remains unverified; perform that check before treating the host as hardened production infrastructure.

Start the controller again, assign a useful task and inspect Work queue/results/receipts. Verify the owner event chain:

```bash
sudo python3 -m dot verify-receipts --config config.json
```

## 9. Run as a service

Copy the package to `/opt/itsnotai-dot`, your completed config to `/etc/itsnotai-dot/config.json`, and install the included service:

```bash
sudo install -d /etc/itsnotai-dot
sudo install -m 0600 config.json /etc/itsnotai-dot/config.json
sudo install -m 0644 scripts/itsnotai-dot.service /etc/systemd/system/itsnotai-dot.service
sudo systemctl daemon-reload
sudo systemctl enable --now itsnotai-dot
```

Remote dashboard access:

```bash
ssh -L 8787:127.0.0.1:8787 your-user@your-vm-host
```

Then open `http://127.0.0.1:8787` locally. Do not expose the privileged controller directly on the internet.

## Operations

The **Computer** panel opens a terminal, performs graceful start/shutdown, and downloads visible workspace files up to 10 MiB. Larger workspaces use SCP over the per-agent management connection. Hidden files are intentionally excluded from browser ZIP exports; artifact manifests and change-budget accounting include them.

Cancel before stopping an active VM. Guest systemd units kill the entire task cgroup. Controller restart polls running guest units instead of repeating submission. If a dispatch was interrupted before its outcome became observable, the job eventually reports `lost`; it is not silently retried. Investigate the guest before manually resubmitting external actions.

Back up the SQLite state, owner token, per-agent SSH keys, guest disks and their immutable backing image together. The host can read its guests and must be trusted. Put VM storage on host-encrypted storage to protect credential caches at rest.

## Recovery and retry behavior (v0.2)

Task requests may include a `request_key` (8–100 letters, digits, underscores or hyphens). Repeating the same key and task for one agent returns the original job, including after a controller restart or completion. Reusing the key for different content is rejected. Keys are scoped to agents. The dashboard generates and retains a key while retrying a submission from the same open task form; closing/reopening the form starts a new request.

Cancellation intent is saved before contacting the guest. If SSH is disconnected, the job remains `cancelling`; when connectivity returns, the controller checks the existing job and retries an idempotent unit stop while it is still running. Completion that occurred before cancellation remains completion. Cancellation does not roll back external effects.

After provisioning was interrupted, use **Computer → Recheck VM**. The controller checks the existing domain name, its assigned disk path and any previously recorded UUID before changing the saved state. A mismatch is rejected. Recheck never creates or deletes a domain, and a recovered running VM must still pass guest health checks.

Guest outcomes use an explicit allowlist. They cannot alter the host's request ID, agent identity, provider, signed lease, prompt or authority receipt. Invalid outcomes remain unresolved with an error instead of being promoted to success. Artifact paths must be relative, unique and within the workspace, with well-formed SHA-256 hashes.

The browser export opens files using directory-relative file descriptors with no symlink following. It compares the bytes with the scanned artifact hash before adding them to the ZIP. A file that changed during export causes failure and should be retried after the task stops.

## Version 0.3 milestone

Start with [docs/MILESTONE.md](docs/MILESTONE.md) after host setup. Existing guests require a stopped-guest source upgrade before protocol 0.3 health checks pass. Use [docs/BOUNDED_DELEGATION.md](docs/BOUNDED_DELEGATION.md) to authorize an approved child VM pool.

## Version 0.4 RAH improvement and compiled guest proof

Read [RAH improvement](docs/RAH_IMPROVEMENT.md) and [kernel/VM reproduction](docs/KERNEL_VM_PROOF.md). The included headless bzImage and minimal initramfs passed actual QEMU guest acceptance. They are test artifacts, not a preconfigured Ubuntu production disk. The normal libvirt host, cloud-init, systemd/firewall and provider sign-in gates still apply. Existing guests need the v0.4 source upgrade to receive `improvement.py`; wire protocol remains 0.3-compatible.
