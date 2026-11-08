"""Explicit budget-capped Vultr fleet creation. Never runs on import."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fleet_provider import VultrFleet

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["plan","apply"])
    p.add_argument("--prefix",required=True)
    p.add_argument("--role",choices=["controller","worker","agent-host"],required=True)
    p.add_argument("--region",required=True)
    p.add_argument("--plan",required=True)
    p.add_argument("--os-id",type=int,required=True)
    p.add_argument("--ssh-key-id",required=True)
    p.add_argument("--count",type=int,required=True)
    p.add_argument("--max-monthly-usd",type=float,required=True)
    p.add_argument("--approve-paid-action",action="store_true")
    args=p.parse_args()
    adapter=VultrFleet()
    plan=adapter.plan(prefix=args.prefix,role=args.role,region=args.region,
        plan=args.plan,os_id=args.os_id,ssh_key_id=args.ssh_key_id,
        count=args.count,max_monthly_usd=args.max_monthly_usd)
    if args.action=="plan":result=plan
    else:result=adapter.apply(plan,approved=args.approve_paid_action)
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__=="__main__":main()
