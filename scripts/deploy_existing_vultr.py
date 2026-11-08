"""Install a reviewed CAPSULA commit onto an existing Vultr controller VM.

No paid VM creation, reinstall, password reset or cloud-init injection.
SSH authenticates using a pinned host key. Secrets travel in SSH stdin, never
in process argv, GitHub source, workflow output or cloud instance user-data.
"""
from __future__ import annotations
import ipaddress
import json
import os
import pathlib
import re
import shlex
import socket
import subprocess
import tempfile
import httpx

API="https://api.vultr.com/v2/instances"
REPO="https://github.com/FreddyCreates/VultrEco.git"
SHA=re.compile(r"^[a-f0-9]{40}$")
USER=re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
FQDN=re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

class DeploymentBlocked(RuntimeError):pass

def allowed_value(name,value,minlength=0):
    if not isinstance(value,str) or len(value)<minlength or "\n" in value or "\r" in value or "\0" in value:
        raise DeploymentBlocked("Missing or invalid "+name)
    return value

def ssh_private_key_value(value):
    if not isinstance(value,str) or len(value)>20000 or chr(13) in value or chr(0) in value:
        raise DeploymentBlocked("Invalid SSH private key")
    pairs=[
        ("-----BEGIN OPENSSH PRIVATE KEY-----","-----END OPENSSH PRIVATE KEY-----"),
        ("-----BEGIN RSA PRIVATE KEY-----","-----END RSA PRIVATE KEY-----"),
        ("-----BEGIN EC PRIVATE KEY-----","-----END EC PRIVATE KEY-----"),
        ("-----BEGIN PRIVATE KEY-----","-----END PRIVATE KEY-----"),
    ]
    if not any(value.startswith(start) and value.strip().endswith(end)
               and len(value)>len(start)+len(end)+64 for start,end in pairs):
        raise DeploymentBlocked("Complete private SSH key required")
    return value

def ssh_known_hosts_value(value):
    if not isinstance(value,str) or not 40<=len(value)<=32768 or chr(0) in value or chr(13) in value:
        raise DeploymentBlocked("Verified SSH known_hosts required")
    entries=[line for line in value.splitlines() if line and not line.startswith("#")]
    if not entries or any(" " not in line or chr(9) in line for line in entries):
        raise DeploymentBlocked("Malformed SSH known_hosts")
    return value

def instance(key,client=None):
    allowed_value("VULTR_API_KEY",key,20)
    owned=client is None
    if owned:client=httpx.Client(timeout=15,trust_env=False,follow_redirects=False)
    try:
        response=client.get(API,headers={"Authorization":"Bearer "+key})
        response.raise_for_status()
        candidates=[v for v in (response.json().get("instances") or [])
            if v.get("label")=="capsula-control" and v.get("region")=="dfw"]
        if len(candidates)!=1:
            raise DeploymentBlocked("Expected exactly one named DFW control VM")
        value=candidates[0]
        if value.get("status")!="active":
            raise DeploymentBlocked("Existing control VM is not active")
        ip=str(value.get("main_ip") or "")
        try:
            addr=ipaddress.ip_address(ip)
            if addr.version!=4 or not addr.is_global:raise ValueError()
        except ValueError as exc:
            raise DeploymentBlocked("Control VM does not have a global IPv4 address") from exc
        return {"instance_id":value.get("id"),"label":"capsula-control","region":"dfw","ip":ip}
    except (httpx.HTTPError,ValueError) as exc:
        raise DeploymentBlocked("Vultr instance discovery failed") from exc
    finally:
        if owned:client.close()

def config(env=None):
    env=env or os.environ
    if env.get("CAPSULA_DEPLOY_APPROVED")!="1":
        raise DeploymentBlocked("Explicit operator deployment approval required")
    key=allowed_value("VULTR_API_KEY",env.get("VULTR_API_KEY",""),20)
    ssh_key=ssh_private_key_value(env.get("CAPSULA_DEPLOY_SSH_KEY",""))
    hosts=ssh_known_hosts_value(env.get("CAPSULA_SSH_KNOWN_HOSTS",""))
    user=env.get("CAPSULA_DEPLOY_SSH_USER","")
    if not USER.fullmatch(user):raise DeploymentBlocked("Explicit SSH account required")
    admin=allowed_value("CAPSULA_ADMIN_API_KEY",env.get("CAPSULA_ADMIN_API_KEY",""),32)
    sha=env.get("GITHUB_SHA","")
    if not SHA.fullmatch(sha):raise DeploymentBlocked("Pinned GitHub commit SHA required")
    fqdn=env.get("CAPSULA_PUBLIC_FQDN","").strip().lower()
    if fqdn and not FQDN.fullmatch(fqdn):
        raise DeploymentBlocked("Invalid public domain")
    inference=env.get("VULTR_INFERENCE_API_KEY","")
    if inference:allowed_value("VULTR_INFERENCE_API_KEY",inference,16)
    return {"key":key,"ssh_key":ssh_key,"hosts":hosts,"user":user,
            "admin":admin,"sha":sha,"fqdn":fqdn,"inference":inference}

def runtime_environment(conf):
    values={
      "CAPSULA_API_KEY":conf["admin"],
      "CAPSULA_DATA":"/app/data",
      "CAPSULA_ALLOW_DIRECT_DOCKER":"0",
      "CAPSULA_DEPLOYMENT_PROVIDER":"vultr"
    }
    if conf["fqdn"]:values["CAPSULA_PUBLIC_FQDN"]=conf["fqdn"]
    if conf["inference"]:
        values.update({
          "CAPSULA_MODEL_PROVIDER":"vultr-serverless",
          "CAPSULA_MODEL_URL":"https://api.vultrinference.com/v1/chat/completions",
          "CAPSULA_MODEL_HOST":"api.vultrinference.com",
          "CAPSULA_MODEL_API_KEY":conf["inference"],
          "VULTR_INFERENCE_API_KEY":conf["inference"]
        })
    return "".join(k+"="+v+"\n" for k,v in values.items()).encode()

def public_dns_matches(domain,ip):
    if not domain:return False
    try:
        return ip in {item[4][0] for item in socket.getaddrinfo(domain,443,type=socket.SOCK_STREAM)}
    except OSError:return False

def deploy(conf=None):
    conf=conf or config()
    vm=instance(conf["key"])
    if not conf["fqdn"] and os.getenv("CAPSULA_AUTO_PUBLIC_TLS")=="1":
        conf={**conf,"fqdn":"capsula."+vm["ip"]+".sslip.io"}
    if conf["fqdn"] and not public_dns_matches(conf["fqdn"],vm["ip"]):
        raise DeploymentBlocked("Public domain does not resolve to the approved control VM")
    with tempfile.TemporaryDirectory(prefix="capsula-deploy-") as t:
        folder=pathlib.Path(t)
        key=folder/"ssh-key";key.write_text(conf["ssh_key"]);key.chmod(0o600)
        known=folder/"known_hosts";known.write_text(conf["hosts"]);known.chmod(0o600)
        match=subprocess.run(["ssh-keygen","-F",vm["ip"],"-f",str(known)],capture_output=True,timeout=5)
        if match.returncode!=0:
            raise DeploymentBlocked("Approved VM IP is missing from pinned SSH known_hosts")
        ssh=["ssh","-T","-i",str(key),"-o","IdentitiesOnly=yes",
             "-o","StrictHostKeyChecking=yes","-o","BatchMode=yes",
             "-o","UserKnownHostsFile="+str(known),"-o","ConnectTimeout=8",
             conf["user"]+"@"+vm["ip"]]
        def run(command,input=None):
            try:
                response=subprocess.run(ssh+["sh -c "+shlex.quote(command)],input=input,
                   capture_output=True,timeout=600,check=False)
            except (subprocess.TimeoutExpired,OSError) as exc:
                raise DeploymentBlocked("SSH command timed out or cannot start") from exc
            if response.returncode:
                # Never expose remote stderr: it may echo .env or other secrets.
                raise DeploymentBlocked("Remote deployment step failed; inspect trusted host logs")
            return response.stdout.decode(errors="replace")
        run("command -v git >/dev/null && command -v docker >/dev/null && docker compose version >/dev/null")
        run("install -d -m 0700 \"$HOME/capsula\" && (test -d \"$HOME/capsula/src/.git\" || git clone --depth=1 "+
            shlex.quote(REPO)+" \"$HOME/capsula/src\")")
        run("cd \"$HOME/capsula/src\" && git fetch --depth=1 origin "+conf["sha"]+
            " && git checkout --detach "+conf["sha"])
        run("umask 077; cat > \"$HOME/capsula/src/.env\" && chmod 0600 \"$HOME/capsula/src/.env\"",
            input=runtime_environment(conf))
        extra=" -f docker-compose.edge.yml" if conf["fqdn"] else ""
        run("cd \"$HOME/capsula/src\" && docker compose -f docker-compose.production.yml"+extra+" up -d --build")
        raw=run("for i in $(seq 1 24); do curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8080/api/health && exit 0; sleep 2; done; exit 1")
        try:status=json.loads(raw)
        except ValueError as exc:raise DeploymentBlocked("Control-plane health is not JSON") from exc
        if status.get("service")!="capsula" or status.get("version")!="0.8.0-alpha.1":
            raise DeploymentBlocked("CAPSULA health version mismatch")
        public=None
        if conf["fqdn"]:
            public="https://"+conf["fqdn"]
            try:
                import time
                verified=False
                with httpx.Client(timeout=12,follow_redirects=False,trust_env=False) as client:
                    for _ in range(18):
                        try:
                            answer=client.get(public+"/api/health")
                            if answer.status_code==200 and answer.json().get("version")=="0.8.0-alpha.1":
                                verified=True
                                break
                        except (httpx.HTTPError,ValueError):
                            pass
                        time.sleep(5)
                if not verified:
                    raise DeploymentBlocked("Public TLS endpoint health failed")
            except (httpx.HTTPError,ValueError) as exc:
                raise DeploymentBlocked("Public HTTPS verification failed") from exc
    return {"provider":"vultr","instance_label":vm["label"],"region":vm["region"],
            "commit":conf["sha"],"control_plane_responding":True,
            "public_url":public,"public_https_verified":bool(public),
            "worker_vm_containment_verified":False,
            "inference_configured":bool(conf["inference"]),
            "inference_live_request_verified":False}

if __name__=="__main__":
    try:
        print(json.dumps(deploy(),sort_keys=True))
    except DeploymentBlocked as exc:
        print("DEPLOYMENT BLOCKED: "+str(exc))
        raise SystemExit(1)
