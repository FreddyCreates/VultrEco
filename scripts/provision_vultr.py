"""Create one CAPSULA Cloud Compute VM on the operator's Vultr account.

Reads VULTR_API_KEY and VULTR_INFERENCE_API_KEY from the environment.
Writes the demo admin token to .vultr-demo-token and prints the public URL.
Does not print either Vultr token. Refuses to create a second capsula-agent-rush VM.
"""
import base64
import json
import os
import secrets
import sys
import time
import pathlib
import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = 'https://api.vultr.com/v2'
LABEL = 'capsula-agent-rush'
PLAN = os.getenv('VULTR_PLAN', 'vc2-1c-2gb')
REGION = os.getenv('VULTR_REGION', 'ewr')


def die(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


def headers(key):
    return {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}


def cloud_init(admin_token, inference_key, chat_model):
    # Tokens are injected into instance user-data. They are not written to the git repo.
    return f"""#cloud-config
package_update: true
packages:
  - python3
  - python3-venv
  - python3-pip
  - docker.io
  - git
  - ca-certificates
write_files:
  - path: /opt/capsula.env
    permissions: "0600"
    content: |
      CAPSULA_API_KEY={admin_token}
      CAPSULA_DATA=/opt/capsula/data
      CAPSULA_ALLOW_DIRECT_DOCKER=1
      CAPSULA_DEPLOYMENT_PROVIDER=vultr
      CAPSULA_MODEL_PROVIDER=vultr-serverless
      CAPSULA_MODEL_URL=https://api.vultrinference.com/v1/chat/completions
      CAPSULA_MODEL_HOST=api.vultrinference.com
      CAPSULA_MODEL_API_KEY={inference_key}
      CAPSULA_MODEL_ALLOWED_MODELS={chat_model}
      VULTR_INFERENCE_API_KEY={inference_key}
      VULTR_CHAT_MODEL={chat_model}
  - path: /etc/systemd/system/capsula.service
    content: |
      [Unit]
      Description=CAPSULA control plane
      After=network-online.target docker.service
      Wants=network-online.target
      [Service]
      WorkingDirectory=/opt/capsula
      EnvironmentFile=/opt/capsula.env
      ExecStart=/opt/capsula/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080
      Restart=on-failure
      [Install]
      WantedBy=multi-user.target
runcmd:
  - systemctl enable --now docker
  - git clone --depth 1 https://github.com/FreddyCreates/VultrEco.git /opt/capsula
  - python3 -m venv /opt/capsula/.venv
  - /opt/capsula/.venv/bin/pip install -r /opt/capsula/requirements.txt
  - docker pull python:3.12-alpine
  - systemctl enable --now capsula.service
"""


def main():
    key = os.getenv('VULTR_API_KEY', '').strip()
    inference = os.getenv('VULTR_INFERENCE_API_KEY', '').strip()
    if not key:
        die('Set VULTR_API_KEY in the environment. It is not stored in the repo.')
    if not inference:
        die('Set VULTR_INFERENCE_API_KEY in the environment. It is not stored in the repo.')
    chat_model = os.getenv('VULTR_CHAT_MODEL', 'mimo-v2.6-flash').strip()
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        listed = client.get(API + '/instances', headers=headers(key))
        if listed.status_code == 401:
            die('Vultr rejected the account token.')
        listed.raise_for_status()
        existing = [item for item in listed.json().get('instances') or [] if item.get('label') == LABEL]
        if existing:
            ip = existing[0].get('main_ip')
            print(json.dumps({'created': False, 'id': existing[0].get('id'), 'main_ip': ip,
                              'demo_url': f'http://{ip}:8080' if ip else None}, indent=2))
            return
        os_list = client.get(API + '/os', headers=headers(key))
        os_list.raise_for_status()
        ubuntu = [item for item in os_list.json().get('os') or []
                  if item.get('arch') == 'x64' and 'Ubuntu 24.04' in (item.get('name') or '')]
        if not ubuntu:
            die('Ubuntu 24.04 x64 was not in the Vultr OS list.')
        admin = secrets.token_urlsafe(48)
        user_data = base64.b64encode(cloud_init(admin, inference, chat_model).encode()).decode()
        created = client.post(API + '/instances', headers=headers(key), json={
            'region': REGION,
            'plan': PLAN,
            'os_id': ubuntu[0]['id'],
            'label': LABEL,
            'hostname': LABEL,
            'user_data': user_data,
            'backups': 'disabled',
            'tags': ['capsula', 'agent-rush'],
        })
        if created.status_code >= 400:
            die('Vultr create failed: ' + created.text[:500])
        instance = created.json().get('instance') or {}
        instance_id = instance.get('id')
        ip = instance.get('main_ip') or ''
        for _ in range(40):
            if ip and ip != '0.0.0.0':
                break
            time.sleep(8)
            polled = client.get(API + '/instances/' + instance_id, headers=headers(key))
            polled.raise_for_status()
            ip = (polled.json().get('instance') or {}).get('main_ip') or ''
        token_path = ROOT / '.vultr-demo-token'
        token_path.write_text(admin + '\n', encoding='utf-8')
        print(json.dumps({
            'created': True,
            'id': instance_id,
            'region': REGION,
            'plan': PLAN,
            'main_ip': ip,
            'demo_url': f'http://{ip}:8080' if ip else None,
            'admin_token_file': str(token_path),
            'note': 'Cloud-init still needs a few minutes to install Docker and start CAPSULA.',
        }, indent=2))


if __name__ == '__main__':
    main()
