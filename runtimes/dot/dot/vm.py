"""Real libvirt/KVM provisioning. There is deliberately no simulated VM backend."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from .guest import checked_id


def run(argv, *, input=None, timeout=30):
    result = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout,
                            env={'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})
    if result.returncode:
        raise RuntimeError(f'{argv[0]} failed ({result.returncode}): {result.stderr[-1200:]}')
    return result.stdout


class Libvirt:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['vm_root']).resolve()
        self.uri = 'qemu:///system'
        self._verified_image = None

    def virsh(self, *args):
        return run(['virsh', '--connect', self.uri, *args])

    def doctor(self):
        required = ['virsh', 'virt-install', 'qemu-img', 'ssh', 'ssh-keygen']
        missing = [x for x in required if not shutil.which(x)]
        kvm = os.access('/dev/kvm', os.R_OK | os.W_OK)
        image = Path(self.config['image']).is_file()
        connection = False
        error = ''
        if not missing:
            try:
                self.virsh('list', '--all')
                connection = True
            except Exception as exc:
                error = str(exc)
        return {'ready': not missing and kvm and image and connection,
                'missing': missing, 'kvm': kvm, 'image': image, 'libvirt': connection, 'error': error}

    def paths(self, agent):
        return self.root / ('dot-' + checked_id(agent['id']))

    def provision(self, agent):
        if not self.doctor()['ready']:
            raise RuntimeError('VM host is not ready; run python3 -m dot doctor --config config.json')
        image = Path(self.config['image']).resolve()
        stat = image.stat()
        fingerprint = (str(image), stat.st_size, stat.st_mtime_ns, self.config['image_sha256'])
        if self._verified_image != fingerprint:
            with image.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            if digest != self.config['image_sha256']:
                raise RuntimeError('Base image SHA-256 mismatch')
            info = json.loads(run(['qemu-img', 'info', '--output=json', str(image)]))
            if info.get('format') != 'qcow2' or info.get('backing-filename'):
                raise RuntimeError('Base image must be a standalone qcow2 image')
            self._verified_image = fingerprint
        folder = self.paths(agent)
        self.root.mkdir(mode=0o711, parents=True, exist_ok=True)
        os.chmod(self.root, 0o711)
        folder.mkdir(mode=0o711, parents=True, exist_ok=False)
        os.chmod(folder, 0o711)
        for key in ('client', 'host'):
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(folder / key)])
        public = (folder / 'client.pub').read_text().strip()
        host_private = (folder / 'host').read_text()
        host_public = (folder / 'host.pub').read_text().strip()
        guest_script = Path(__file__).with_name('guest.py').read_text()
        gateway = self.config['gateway']
        # Root-owned guest firewall blocks access to host, other guests, metadata and private LANs.
        firewall = f'''table inet dot {{
 chain output {{ type filter hook output priority 0; policy accept;
  oifname "lo" accept
  ct state established,related accept
  ip daddr {gateway} udp dport 53 accept
  ip daddr {gateway} tcp dport 53 accept
  udp sport 68 udp dport 67 accept
  ip daddr {{ 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 }} reject
  meta nfproto ipv6 reject
 }}
 chain input {{ type filter hook input priority 0; policy drop;
  iifname "lo" accept
  ct state established,related accept
  ip saddr {gateway} tcp dport 22 accept
  udp sport 67 udp dport 68 accept
 }}
}}
'''
        config_toml = 'forced_login_method = "chatgpt"\ncli_auth_credentials_store = "file"\n[sandbox_workspace_write]\nnetwork_access = true\n'
        settings = json.dumps({'security': {'auth': {'selectedType': 'oauth-personal'}}, 'tools': {'sandbox': False}, 'telemetry': {'enabled': False}})
        writes = [{'path': '/opt/dot/guest.py', 'content': guest_script, 'permissions': '0755'},
                  {'path': '/etc/nftables.conf', 'content': firewall, 'permissions': '0600'},
                  {'path': '/home/dot/.codex/config.toml', 'content': config_toml, 'owner': 'dot:dot', 'permissions': '0600'},
                  {'path': '/home/dot/.gemini/settings.json', 'content': settings, 'owner': 'dot:dot', 'permissions': '0600'},
                  {'path': '/etc/ssh/sshd_config.d/90-dot.conf', 'content': 'PasswordAuthentication no\nPermitRootLogin no\nAllowUsers dot\nAllowAgentForwarding no\n', 'permissions': '0644'}]
        cloud = {'hostname': 'dot-' + agent['id'][:12], 'disable_root': True, 'ssh_pwauth': False,
                 'users': [{'name': 'dot', 'shell': '/bin/bash', 'lock_passwd': True, 'sudo': False,
                            'groups': [], 'ssh_authorized_keys': [public]}],
                 'ssh_keys': {'ed25519_private': host_private, 'ed25519_public': host_public},
                 'package_update': True, 'packages': ['python3', 'python3-venv', 'git', 'curl', 'nftables', 'ca-certificates'],
                 'write_files': writes, 'runcmd': [
                    ['bash', '-ec', 'test "$(node -p \'parseInt(process.versions.node)\')" -ge 20'],
                    ['npm', 'install', '-g', '@openai/codex@' + self.config['codex_version'], '@google/gemini-cli@' + self.config['gemini_version']],
                    ['install', '-d', '-o', 'dot', '-g', 'dot', '-m', '0700', '/home/dot/workspace', '/home/dot/.dot'],
                    ['loginctl', 'enable-linger', 'dot'], ['systemctl', 'enable', '--now', 'nftables'],
                    ['bash', '-ec', 'codex --version && gemini --version && systemctl is-active nftables && test -f /home/dot/.codex/config.toml && nft list ruleset > /opt/dot/firewall.rules && chmod 0644 /opt/dot/firewall.rules && touch /opt/dot/ready']
                 ]}
        for name in ('checkpoint.py', 'verification.py', 'computer.py', 'delegation.py', 'improvement.py'):
            writes.append({'path': '/opt/dot/' + name, 'content': Path(__file__).with_name(name).read_text(), 'permissions': '0644'})
        # JSON is a YAML subset supported by cloud-init.
        seed = folder / 'user-data'
        seed.write_text('#cloud-config\n' + json.dumps(cloud))
        os.chmod(seed, 0o600)
        disk = folder / 'disk.qcow2'
        run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(image), str(disk), str(agent['disk_gb']) + 'G'])
        shutil.chown(disk, user=self.config.get('qemu_user', 'libvirt-qemu'))
        os.chmod(disk, 0o600)
        # Each agent gets a separate writable disk; base image is read-only shared storage.
        run(['virt-install', '--connect', self.uri, '--name', agent['domain'], '--memory', str(agent['memory_mb']),
             '--vcpus', str(agent['vcpus']), '--cpu', 'host-passthrough', '--import', '--osinfo', 'ubuntu24.04',
             '--disk', f'path={disk},format=qcow2,bus=virtio', '--network', 'network=' + self.config['network'] + ',model=virtio',
             '--cloud-init', 'user-data=' + str(seed), '--graphics', 'none', '--noautoconsole', '--wait', '0'], timeout=90)
        self.virsh('autostart', agent['domain'])
        return self.virsh('domuuid', agent['domain']).strip()

    def address(self, agent):
        output = self.virsh('domifaddr', agent['domain'], '--source', 'lease')
        for line in output.splitlines():
            for word in line.split():
                try:
                    address = ipaddress.ip_interface(word)
                    if address.version == 4 and address.ip in ipaddress.ip_network(self.config['subnet']):
                        return str(address.ip)
                except ValueError:
                    pass
        raise RuntimeError('VM has no DHCP lease yet')

    def ssh_command(self, agent, *command, tty=False):
        ip = self.address(agent)
        folder = self.paths(agent)
        pub = (folder / 'host.pub').read_text().split()
        known = folder / 'known_hosts'
        known.write_text(ip + ' ' + ' '.join(pub[:2]) + '\n')
        os.chmod(known, 0o600)
        argv = ['ssh', '-i', str(folder / 'client'), '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'UserKnownHostsFile=' + str(known), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3']
        if tty:
            argv += ['-t']
        return argv + ['dot@' + ip, shlex.join(command)]

    def guest(self, agent, action, *args, data=None):
        return json.loads(run(self.ssh_command(agent, 'python3', '/opt/dot/guest.py', action, *args),
                              input=json.dumps(data) if data is not None else None, timeout=45))

    def start(self, agent):
        self.virsh('start', agent['domain'])

    def stop(self, agent):
        self.virsh('shutdown', agent['domain'])

    def state(self, agent):
        return self.virsh('domstate', agent['domain']).strip()

    def inspect(self, agent):
        root = ET.fromstring(self.virsh('dumpxml', agent['domain']))
        if root.findtext('name') != agent['domain']:
            raise ValueError('Domain identity mismatch')
        expected = str(self.paths(agent) / 'disk.qcow2')
        disks = [node.get('file') for node in root.findall("./devices/disk[@device='disk']/source")]
        if disks != [expected]:
            raise ValueError('Domain disk does not match this agent')
        identity = root.findtext('uuid')
        if not identity or (agent.get('domain_uuid') and agent['domain_uuid'] != identity):
            raise ValueError('Domain UUID mismatch')
        return {'domain_uuid': identity, 'power_state': self.state(agent)}
