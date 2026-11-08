#!/usr/bin/env bash
set -euo pipefail
# Ubuntu 24.04 host. Requires physical/nested virtualization, not a normal container.
if [[ $EUID != 0 ]]; then echo 'Run with sudo on your Linux VM host.' >&2; exit 1; fi
if [[ ! -e /dev/kvm ]]; then echo 'KVM is unavailable. Enable virtualization or choose a host that supports it.' >&2; exit 1; fi
apt-get update
apt-get install -y python3 qemu-kvm qemu-utils libvirt-daemon-system libvirt-clients virtinst libguestfs-tools openssh-client build-essential flex bison libssl-dev libelf-dev bc dwarves debhelper rsync xz-utils npm
systemctl enable --now libvirtd
if ! virsh net-info default >/dev/null 2>&1; then echo 'Define the libvirt default NAT network before proceeding.' >&2; exit 1; fi
if ! virsh net-info default | awk '/Active:/{print $2}' | sed -n '1p' | grep -q '^yes$'; then virsh net-start default; fi
virsh net-autostart default
install -d -m 0711 /var/lib/libvirt/images/itsnotai-dot
install -d -m 0700 /var/lib/itsnotai-dot
printf '%s\n' 'Host dependencies installed. Prepare the verified base image next; see DEPLOYMENT.md.'
