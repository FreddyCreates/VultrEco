"""CAPSULA multi-host Vultr capacity planner/provisioner.

Paid operations are explicitly opt-in, idempotent by instance label and bounded
by observed plan monthly price. No secrets or worker tokens enter cloud-init.
"""
from __future__ import annotations
import base64
import os
import re
import time
import httpx

API="https://api.vultr.com/v2"
LABEL=re.compile(r"^[a-z][a-z0-9-]{3,47}$")
ROLES=("controller","worker","agent-host")
KIND=re.compile(r"^[a-z0-9-]{2,40}$")

class ProvisionError(RuntimeError): pass

def headers(key):
    if not key:raise ProvisionError("VULTR_API_KEY unavailable")
    return {"Authorization":"Bearer "+key,"Content-Type":"application/json"}

class VultrFleet:
    def __init__(self,key=None,client=None):
        self.key=key or os.getenv("VULTR_API_KEY","")
        self.client=client
        if not self.key:raise ProvisionError("Vultr API key is not configured")

    def get(self,path):
        with httpx.Client(timeout=20,follow_redirects=False,trust_env=False) if self.client is None else _NoClose(self.client) as http:
            try:
                res=http.get(API+path,headers=headers(self.key))
                res.raise_for_status()
                return res.json()
            except (httpx.HTTPError,ValueError) as exc:
                raise ProvisionError("Vultr read failed; check API access/IP allowlist") from exc

    def post(self,path,body):
        with httpx.Client(timeout=25,follow_redirects=False,trust_env=False) if self.client is None else _NoClose(self.client) as http:
            try:
                res=http.post(API+path,headers=headers(self.key),json=body)
                res.raise_for_status()
                return res.json()
            except (httpx.HTTPError,ValueError) as exc:
                raise ProvisionError("Vultr provisioning request failed; reconcile by label before retrying") from exc

    def plan(self, *, prefix, region, plan, os_id, count, role, ssh_key_id, max_monthly_usd):
        if not LABEL.fullmatch(prefix) or role not in ROLES or not KIND.fullmatch(region):
            raise ProvisionError("Invalid fleet identity/role/region")
        if not isinstance(plan,str) or not KIND.fullmatch(plan):
            raise ProvisionError("Invalid compute plan identifier")
        if type(os_id) is not int or os_id<=0 or not isinstance(ssh_key_id,str) or not ssh_key_id:
            raise ProvisionError("Explicit OS image and trusted SSH key ID required")
        if type(count) is not int or not 1<=count<=8:
            raise ProvisionError("Fleet expansion limited to 1-8 hosts per operation")
        if type(max_monthly_usd) not in (int,float) or not 1<=max_monthly_usd<=10000:
            raise ProvisionError("Explicit total monthly USD budget cap required")
        plans=self.get("/plans").get("plans") or []
        selected=next((x for x in plans if x.get("id")==plan),None)
        if not selected:raise ProvisionError("Requested plan not verified against provider catalog")
        try:monthly=float(selected["monthly_cost"])
        except (TypeError,ValueError,KeyError) as exc:
            raise ProvisionError("Provider plan price unavailable: refusing paid action") from exc
        if not 0<monthly*count<=max_monthly_usd:
            raise ProvisionError("Requested fleet exceeds approved monthly budget")
        instances=self.get("/instances").get("instances") or []
        labels=[f"{prefix}-{role}-{i:02}" for i in range(1,count+1)]
        existing={i.get("label"):i for i in instances if i.get("label") in labels}
        for item in existing.values():
            if item.get("region")!=region or item.get("plan")!=plan:
                raise ProvisionError("Existing instance label conflicts with requested region/plan")
        return {"prefix":prefix,"role":role,"region":region,"plan":plan,
                "os_id":os_id,"ssh_key_id":ssh_key_id,
                "count":count,"monthly_usd_estimate":round(monthly*count,2),
                "monthly_usd_cap":max_monthly_usd,
                "existing":[{"label":label,"id":existing[label].get("id")} for label in labels if label in existing],
                "missing":[label for label in labels if label not in existing],
                "monthly_cost_per_host":monthly,
                "provider":"vultr","secrets_in_user_data":False}

    @staticmethod
    def bootstrap(role):
        # No API keys, signing keys, tokens, or executable untrusted workloads.
        # Only package bootstrap. Host enrollment happens over authenticated SSH.
        return """#cloud-config
package_update: true
packages:
  - ca-certificates
  - curl
  - docker.io
  - nftables
  - python3
users:
  - default
write_files:
  - path: /etc/capsula-host-role
    permissions: '0644'
    content: '""" + role + """'
runcmd:
  - [ systemctl, enable, --now, docker ]
  - [ systemctl, enable, --now, nftables ]
"""

    def apply(self,plan,approved=False):
        if not approved or os.getenv("CAPSULA_DEPLOY_APPROVED")!="1":
            raise ProvisionError("Explicit paid provisioning approval is required")
        if not isinstance(plan,dict) or plan.get("provider")!="vultr":
            raise ProvisionError("Use a verified VultrFleet.plan result")
        # Refetch catalog/account/instances before spending; never reuse untrusted
        # price data from a forged saved plan.
        check=self.plan(prefix=plan["prefix"],role=plan["role"],region=plan["region"],
                        plan=plan["plan"],os_id=plan["os_id"],count=plan["count"],
                        ssh_key_id=plan["ssh_key_id"],max_monthly_usd=plan["monthly_usd_cap"])
        created=[]
        for label in check["missing"]:
            response=self.post("/instances",{
                "label":label,"hostname":label,"region":check["region"],
                "plan":check["plan"],"os_id":check["os_id"],
                "sshkey_id":[check["ssh_key_id"]],
                "user_data":base64.b64encode(self.bootstrap(check["role"]).encode()).decode(),
                "backups":"disabled","tags":["capsula","fleet",check["role"]],
            })
            instance=response.get("instance") or {}
            created.append({"label":label,"id":instance.get("id"),"state":"provisioning"})
        return {"created":created,"reused":check["existing"],
                "monthly_usd_estimate":check["monthly_usd_estimate"],
                "security":"No cloud credentials in instance user-data; registration pending",
                "runtime_verified":False}

class _NoClose:
    def __init__(self,client):self.client=client
    def __enter__(self):return self.client
    def __exit__(self,*args):return False
