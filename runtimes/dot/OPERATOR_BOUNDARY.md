# Trust and authority boundary

This is a **single-owner privileged Linux host controller**. The owner token is a bearer capability to create VMs and authorize tasks. It also serves as the host-side HMAC mission authority. Agent VMs never receive this token. The controller runs as root for libvirt/storage operations; it must be hosted on a trusted dedicated machine.

Every VM agent runs as the `dot` Linux user without sudo. Agent tasks can manipulate their own workspace and user-level files. Gemini work mode authorizes tools inside the whole guest-user boundary, including access to that user's own provider cache. The VM and root-owned firewall form its host boundary; its home directory is not a separate secret sandbox against its own agent.

Mission scope is checked in the host before dispatch. The HMAC signature is not independently verified by the guest, which receives execution data through a pinned SSH channel. The guest checks scope/expiration and observes change budgets. Treat guest-reported outcomes as operational evidence, not remote-attestation proofs against a compromised guest.

Time, process and memory limits are enforced through systemd/cgroups. Workspace changes are scanned periodically and at completion. A budget violation terminates the task, but earlier writes remain: this is detection and stopping, not transactional rollback or prevention of every transient write. VM disk size bounds overall storage. No token/spend quota is centrally enforced; subscription usage is governed by provider accounts.

The guest firewall permits public networking, guest DNS through the host gateway and established management replies. New private/LAN/metadata connections are rejected and IPv6 outbound is rejected. It restricts inbound SSH to the host gateway. Confirm routing/firewall behavior on the actual host; the source tests do not prove live network isolation.

There are no host-shell execution endpoints and no shared writable host mounts. Opt-in recursive delegation is confined to an owner-approved pool of existing agent VMs, with inherited deadlines and shared reservations. Each child receives authority only inside its assigned VM; it cannot provision paid hosts or extend the pool. Production deployment intent is declared out of scope, but public network access can produce external effects if an owner later installs external credentials: policy labels alone cannot prevent every such effect.

Encrypted CAPSULA imports retain the source's ciphertext envelope and hash lineage. This runtime stores the envelope and import receipt; it does not decrypt a VAUL computer, execute its contents, or validate a cipher's authenticity without the originating VAUL keys. It does not mint new permissions from imported JSON.

Guest disks and cloud-init seed files contain sensitive keys. This release relies on trusted host permissions and optional host LUKS encryption; it does not claim encrypted qcow2 by default. Backups need equivalent protection. Providers share the owner's account limits across agents.

The hash-linked owner event chain is local tamper evidence against a retained chain tip, not a third-party signature or external audit. It records action/results, not private model reasoning.

Workspace checkpoints and their recovery journals live under the guest agent user. They support operational recovery, not tamper-proof evidence against that same user. Guest-local browser profiles are likewise part of the agent-user boundary. Provider caches are not copied into checkpoint snapshots.

The RAH improvement lab executes owner-supplied verifier Python. A separate process, scratch HOME and directory copy do not isolate hostile code from same-user files. Run untrusted trials in disposable credential-free VMs. Same-user lab hashes/checkpoints are operational evidence, not an independent authority service. Enterprise namespace labels do not establish tenant isolation. See `docs/RAH_IMPROVEMENT.md`.
