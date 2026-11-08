# Reproducing Linux guest and improvement acceptance

The release distinguishes the custom Linux image, CPU-emulated Linux guests, hardware KVM/libvirt provisioning, provider inference and browser rendering. Inspect the receipts for their individual evidence; none implies the others.

## Source and build

Use the exact upstream archive and SHA-256 in `kernel/source-info.json`. The archive is checked against the publisher checksum index downloaded over TLS. The PGP signature of that index was not verified. Source is provided separately with the release, plus the upstream download URL.

Install ordinary kernel build dependencies on a build host (compiler, make, binutils, flex, bison, bc, libelf/OpenSSL development headers, pkgconf). Then:

```bash
python3 scripts/build_kernel.py --archive /path/linux-source.tar.xz --sha256 EXACT_SOURCE_SHA256 --out /path/kernel-build --jobs 6 --image-only --headless
```

`--headless` omits DRM, sound, wireless, media and USB support from the x86-64 default configuration merged with `kernel/dot.config`. The exact compiled configuration is included. This image-only target does not compile/install a Debian package or prove that an Ubuntu qcow2 image was upgraded. Use the default package target and the separate installation/real-host acceptance workflow for production guests.

## Real guest test

Supply a local extracted Ubuntu toolchain tree containing QEMU, SeaBIOS and busybox-static. `scripts/build_probe_root.py` builds a credential-free BusyBox/Python initramfs from local Python 3.12 and its shared libraries, and the project source/tests. It copies no provider caches, user home contents or network configuration.

```bash
python3 scripts/build_probe_root.py --out /path/probe-root --toolchain /path/extracted-tools --project /path/itsnotai-dot
python3 scripts/verify_qemu.py --kernel /path/bzImage --initrd /path/probe-root/guest-root.cpio.gz --qemu /path/extracted-tools/usr/bin/qemu-system-x86_64 --toolchain /path/extracted-tools --out /path/new-boot-results
```

The verifier creates two separate raw ext4 disks and two VM UUIDs. It boots each VM twice under QEMU TCG without a network interface. Guest work runs as UID 1000. The first boot runs improvement tests and promotes a real procedure change; the second boot verifies persistence under a new Linux boot ID and rolls it back. Receipts retain guest proofs and serial-log hashes.

This uses an actual Linux guest kernel with CPU emulation, not a container or a fabricated provider response. It does not prove hardware KVM, production libvirt provisioning, cloud-init, systemd units, guest firewall behavior, real provider authentication/inference or Chromium rendering. No production VM is modified by the probe.

The minimal initramfs is for acceptance only. It is not the persistent Ubuntu agent image and does not contain installed Codex, Gemini or Chromium. Rebuild it after source changes before claiming the resulting guest test covers those changes.

## Browser acceptance

The separate browser probe uses Python Playwright 1.62.0 and the official Chrome for Testing build recorded in `receipts/historical-v0.4/browser-toolchain.json`. Build a larger temporary initramfs with `--browser-dir` pointing to the extracted `chrome-linux64` and `--browser-python` pointing to a local Playwright installation. Then use `scripts/verify_browser_vm.py` with the same kernel and extracted toolchain. This browser image is intentionally not bundled; the small bundled initramfs runs the improvement tests only.

`DOT_BROWSER_EXECUTABLE` optionally selects an existing absolute browser executable in `dot/computer.py`. Without it, the normal installed Playwright Chromium is used. The guest probe actually navigates, fills/clicks the owner-token form, waits for visible authenticated controls, inspects text and captures a screenshot. It also tests mobile layout, mission navigation, the unavailable-host message and refusal to create a phantom agent. Screenshot hashes are retained as evidence; screenshots are internal visual QA and are not included in the release.

The first minimal bootstrap failed because its gzip stream was incomplete. That negative result is preserved in `receipts/historical-v0.4/guest-bootstrap-failure.json`. The builder now writes a complete newc archive, compresses it using gzip, and checks gzip integrity before returning. Successful subsequent boots use the repaired archive; the failed bootstrap is not counted as a passed guest test.

A later browser repro exposed `/tmp` archived with mode 0755, which prevented the unprivileged browser from creating temporary files. The builder now encodes mode 01777 explicitly and initializes it in guest boot. That negative result is retained separately in `receipts/historical-v0.4/browser-bootstrap-failure.json`.
