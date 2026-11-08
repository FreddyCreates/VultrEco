"""Live Vultr account and Cloud Compute calls.

Tokens stay in the environment. Returned payloads omit email, billing ids, and secrets.
"""
import os
import httpx

API = 'https://api.vultr.com/v2'
INFERENCE_ORIGIN = 'https://api.vultrinference.com'
CHAT_COMPLETIONS = INFERENCE_ORIGIN + '/v1/chat/completions'
DEFAULT_CHAT_MODEL = 'mimo-v2.6-flash'


def account_token():
    return os.getenv('VULTR_API_KEY', '').strip()


def inference_token():
    return os.getenv('VULTR_INFERENCE_API_KEY', '').strip()


def _client():
    return httpx.Client(timeout=20, follow_redirects=False, trust_env=False)


def snapshot():
    """Account balance and instance list. Never includes the bearer token."""
    key = account_token()
    if not key:
        return {'configured': False, 'account': None, 'instances': [], 'error': None,
                'inference_configured': bool(inference_token()),
                'inference_origin': INFERENCE_ORIGIN}
    headers = {'Authorization': 'Bearer ' + key}
    try:
        with _client() as client:
            account = client.get(API + '/account', headers=headers)
            account.raise_for_status()
            body = (account.json() or {}).get('account') or {}
            listed = client.get(API + '/instances', headers=headers)
            listed.raise_for_status()
            raw = (listed.json() or {}).get('instances') or []
    except httpx.HTTPError:
        return {'configured': True, 'account': None, 'instances': [], 'error': 'vultr-api-failed',
                'inference_configured': bool(inference_token()),
                'inference_origin': INFERENCE_ORIGIN}
    instances = [{
        'id': item.get('id'),
        'label': item.get('label'),
        'region': item.get('region'),
        'plan': item.get('plan'),
        'status': item.get('status'),
        'power_status': item.get('power_status'),
        'main_ip': item.get('main_ip'),
        'os': item.get('os'),
    } for item in raw[:20]]
    return {
        'configured': True,
        'error': None,
        'account': {
            'name': body.get('name'),
            'balance': body.get('balance'),
            'pending_charges': body.get('pending_charges'),
        },
        'instances': instances,
        'inference_configured': bool(inference_token()),
        'inference_origin': INFERENCE_ORIGIN,
        'default_chat_model': os.getenv('VULTR_CHAT_MODEL', DEFAULT_CHAT_MODEL),
    }
