"""Vultr live adapter stays secret-free and fail-closed without tokens."""
from capsula.providers.vultr import vultr_cloud
from capsula.intelligence import inference


def test_live_route_requires_auth_and_stays_quiet(monkeypatch):
    monkeypatch.delenv('VULTR_API_KEY', raising=False)
    monkeypatch.delenv('VULTR_INFERENCE_API_KEY', raising=False)
    from test_api_v2 import c, auth
    assert c.get('/api/vultr/live').status_code == 401
    body = c.get('/api/vultr/live', headers=auth).json()
    assert body['configured'] is False
    assert 'API_KEY' not in str(body)


def test_snapshot_unconfigured(monkeypatch):
    monkeypatch.delenv('VULTR_API_KEY', raising=False)
    monkeypatch.delenv('VULTR_INFERENCE_API_KEY', raising=False)
    status = vultr_cloud.snapshot()
    assert status['configured'] is False
    assert status['instances'] == []
    assert 'API_KEY' not in str(status)


def test_inference_preset_uses_vultr_serverless(monkeypatch):
    monkeypatch.setenv('VULTR_INFERENCE_API_KEY', 'unit-test-secret')
    for name in ('CAPSULA_MODEL_URL', 'VULTR_INFERENCE_URL', 'CAPSULA_MODEL_ALLOWED_MODELS',
                 'VULTR_ALLOWED_MODELS', 'CAPSULA_MODEL_HOST', 'VULTR_INFERENCE_HOST', 'CAPSULA_MODEL_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('CAPSULA_MODEL_PROVIDER', 'self-hosted')
    cfg = inference.config()
    assert cfg['configured'] is True
    assert cfg['provider'] == 'vultr-serverless'
    assert cfg['endpoint'] == 'https://api.vultrinference.com/v1/chat/completions'
    assert cfg['models'] == ['mimo-v2.6-flash']
    public = inference.public_config()
    assert 'unit-test-secret' not in str(public)
    assert 'key' not in public
