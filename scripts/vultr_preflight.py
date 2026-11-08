"""Read-only provider preflight. No credential, PII or billing details emitted."""
import json
import os
import sys
import httpx

def check():
    token=os.getenv("VULTR_API_KEY","")
    if not token:
        return {"cloud_api":"not-configured","inference_key_present":bool(os.getenv("VULTR_INFERENCE_API_KEY"))}
    try:
        with httpx.Client(timeout=12,trust_env=False,follow_redirects=False) as client:
            account=client.get("https://api.vultr.com/v2/account",
                headers={"Authorization":"Bearer "+token})
            instances=client.get("https://api.vultr.com/v2/instances",
                headers={"Authorization":"Bearer "+token})
        return {"cloud_api":"reachable" if account.status_code==200 and instances.status_code==200 else "not-verified",
                "account_http_status":account.status_code,"instances_http_status":instances.status_code,
                "inference_key_present":bool(os.getenv("VULTR_INFERENCE_API_KEY")),
                "live_deployment_verified":False}
    except httpx.HTTPError:
        return {"cloud_api":"network-error","inference_key_present":bool(os.getenv("VULTR_INFERENCE_API_KEY")),
                "live_deployment_verified":False}

if __name__=="__main__":
    status=check()
    print(json.dumps(status,sort_keys=True))
    sys.exit(0 if status.get("cloud_api")=="reachable" else 1)
