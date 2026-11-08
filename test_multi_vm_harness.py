"""Real-VM harness rejects unsafe and fake host declarations before any I/O."""
import json
import pytest
from scripts.benchmark_multi_vm import targets_from_env,run_live

def base():
    return {"CAPSULA_LIVE_VM_TARGETS":json.dumps([
        {"id":"vm-001","origin":"https://worker-one.example","token_env":"CAPSULA_LIVE_TOKEN_FIRST"},
        {"id":"vm-002","origin":"https://worker-two.example","token_env":"CAPSULA_LIVE_TOKEN_SECOND"}]),
        "CAPSULA_LIVE_TOKEN_FIRST":"unit-only","CAPSULA_LIVE_TOKEN_SECOND":"unit-only"}

def test_requires_two_distinct_hosts():
    d=base()
    assert len(targets_from_env(d))==2
    for n in ([],[json.loads(d["CAPSULA_LIVE_VM_TARGETS"])[0]]):
        d["CAPSULA_LIVE_VM_TARGETS"]=json.dumps(n)
        with pytest.raises(ValueError):targets_from_env(d)

def test_rejects_duplicate_endpoints():
    d=base()
    nodes=json.loads(d["CAPSULA_LIVE_VM_TARGETS"])
    nodes[1]["origin"]=nodes[0]["origin"]
    d["CAPSULA_LIVE_VM_TARGETS"]=json.dumps(nodes)
    with pytest.raises(ValueError):targets_from_env(d)

def test_rejects_plaintext_or_local_origins():
    d=base()
    nodes=json.loads(d["CAPSULA_LIVE_VM_TARGETS"])
    for origin in ("http://worker.example","http://localhost:8081","https://user:pass@worker.example","https://worker.example/evil"):
        nodes[0]["origin"]=origin
        d["CAPSULA_LIVE_VM_TARGETS"]=json.dumps(nodes)
        with pytest.raises(ValueError):targets_from_env(d)

def test_rejects_inline_credentials():
    d=base()
    nodes=json.loads(d["CAPSULA_LIVE_VM_TARGETS"])
    nodes[0]["token_env"]="VULTR_API_KEY"
    d["CAPSULA_LIVE_VM_TARGETS"]=json.dumps(nodes)
    with pytest.raises(ValueError):targets_from_env(d)

def test_real_execution_is_opt_in(monkeypatch):
    monkeypatch.delenv("CAPSULA_LIVE_VM_TEST_APPROVED",raising=False)
    with pytest.raises(RuntimeError):run_live()
