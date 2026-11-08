"""Existing control VM deployment preflight is fail closed and secret-free."""
import pytest
from scripts.deploy_existing_vultr import config,instance,allowed_value,DeploymentBlocked,runtime_environment

def env():
    return {
      "CAPSULA_DEPLOY_APPROVED":"1","VULTR_API_KEY":"v"*40,
      "CAPSULA_DEPLOY_SSH_KEY":"-----BEGIN OPENSSH PRIVATE KEY-----\n"+"A"*120+"\n-----END OPENSSH PRIVATE KEY-----",
      "CAPSULA_SSH_KNOWN_HOSTS":"1.2.3.4 ssh-ed25519 AAAAUNITTESTONLYAAAAAAAABBBB",
      "CAPSULA_DEPLOY_SSH_USER":"ubuntu",
      "CAPSULA_ADMIN_API_KEY":"a"*48,
      "GITHUB_SHA":"a"*40,
      "CAPSULA_PUBLIC_FQDN":"capsula.example.com",
      "VULTR_INFERENCE_API_KEY":""
    }

def test_deploy_requires_explicit_grant():
    e=env();e["CAPSULA_DEPLOY_APPROVED"]="0"
    with pytest.raises(DeploymentBlocked):config(e)

def test_deploy_validates_ssh_user():
    e=env();e["CAPSULA_DEPLOY_SSH_USER"]="ubuntu;echo unsafe"
    with pytest.raises(DeploymentBlocked):config(e)

def test_deploy_rejects_newline_secrets():
    e=env();e["CAPSULA_ADMIN_API_KEY"]+="\nBAD=1"
    with pytest.raises(DeploymentBlocked):config(e)

def test_deploy_requires_commit_pin():
    e=env();e["GITHUB_SHA"]="main"
    with pytest.raises(DeploymentBlocked):config(e)

def test_deploy_no_cloud_key_in_envfile():
    e=config(env())
    contents=runtime_environment(e).decode()
    assert "VULTR_API_KEY" not in contents
    assert "CAPSULA_ALLOW_DIRECT_DOCKER=0" in contents
    assert "CAPSULA_API_KEY=" in contents

def test_deploy_rejects_invalid_domain():
    e=env();e["CAPSULA_PUBLIC_FQDN"]="http://bad.example.com"
    with pytest.raises(DeploymentBlocked):config(e)

def test_deploy_accepts_real_newline_formatted_secrets():
    e=env()
    e["CAPSULA_SSH_KNOWN_HOSTS"] += "\n1.2.3.4 ssh-rsa AAAADUMMYCHECK"
    result=config(e)
    assert "\n" in result["ssh_key"]
    assert "\n" in result["hosts"]

def test_deploy_rejects_carriage_return_and_nul():
    for key in ("CAPSULA_DEPLOY_SSH_KEY","CAPSULA_SSH_KNOWN_HOSTS"):
        for marker in ("\r","\x00"):
            e=env()
            e[key] += marker
            with pytest.raises(DeploymentBlocked):
                config(e)

def test_release_deployment_script_verifies_v08():
    from pathlib import Path
    code=Path("scripts/deploy_existing_vultr.py").read_text()
    assert "0.8.0-alpha.1" in code
    assert "0.7.0-alpha.1" not in code

def test_autodomain_not_created_without_operator_flag(monkeypatch):
    monkeypatch.delenv("CAPSULA_AUTO_PUBLIC_TLS",raising=False)
    assert config(env())["fqdn"]=="capsula.example.com"
