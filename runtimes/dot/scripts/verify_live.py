#!/usr/bin/env python3
"""Acceptance gate on a REAL KVM host after owner subscription login. Never uses fixture backends."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dot.core import load_config
from dot.vm import Libvirt,run
import sqlite3
import uuid
from dot.kernel import CapabilityKernel
from dot.verification import evidence_matches

p=argparse.ArgumentParser()
p.add_argument('--config',default='config.json')
p.add_argument('--agents',nargs='+',required=True)
p.add_argument('--recovery',action='store_true',help='Also interrupt a real guest job, restore its checkpoint and resume provider work')
p.add_argument('--out',default='receipts/live-acceptance.json')
a=p.parse_args()
c=load_config(a.config);b=Libvirt(c)
if not b.doctor()['ready']:raise SystemExit('BLOCKED: VM hypervisor is not ready')
root=Path(c['state_dir']);kernel=CapabilityKernel((root/'owner.token').read_text().strip())
checks=[];seen=set();providers=set()
with sqlite3.connect(root/'dot.sqlite3') as db:
    for agent_id in a.agents:
        row=db.execute('SELECT data FROM agents WHERE id=?',(agent_id,)).fetchone()
        if not row:raise SystemExit('Unknown agent')
        agent=json.loads(row[0]);health=b.guest(agent,'health')
        domain_uuid=b.virsh('domuuid',agent['domain']).strip()
        if domain_uuid in seen:raise SystemExit('VM identity reused across agents')
        seen.add(domain_uuid)
        if health.get('protocol_version') != '0.3':raise SystemExit('Guest source upgrade required before live verification')
        if not health['ready']:raise SystemExit('Guest is not ready')
        if c.get('expected_kernel') and health['kernel_release']!=c['expected_kernel']:raise SystemExit('Custom Linux kernel was not booted')
        if health['uid']==0:raise SystemExit('Agent is running as root')
        active=db.execute('SELECT data FROM jobs WHERE agent_id=?',(agent_id,)).fetchall()
        if any(json.loads(r[0])['status'] not in ('completed','failed','cancelled','lost') for r in active):
            raise SystemExit('Agent has an active task. Let it complete before acceptance.')
        job_id=uuid.uuid4().hex
        job={'id':job_id,'provider':agent['provider'],'prompt':'Write the exact text DOT_VM_ACCEPTANCE_OK to dot-acceptance.txt in your current workspace. Read it back and reply with that exact text. Do not access other files or network services.','model':'','mode':'work','timeout':120}
        job['acceptance']={'files':[{'path':'dot-acceptance.txt','contains':'DOT_VM_ACCEPTANCE_OK'}]}
        job['lease']=kernel.issue(job_id=job_id,agent_id=agent_id,timeout=120,mode='work',changed_bytes=4096)
        # Real CLI inference. No stubs. A zero exit alone is insufficient.
        b.guest(agent,'submit',data=job)
        deadline=time.time()+150
        while time.time()<deadline:
            result=b.guest(agent,'status',job_id)
            if result['status']!='running':break
            time.sleep(2)
        if result['status']!='completed' or 'DOT_VM_ACCEPTANCE_OK' not in result.get('response',''):
            raise SystemExit('Provider acceptance failed: '+json.dumps(result))
        if not result.get('checkpoint_id') or not evidence_matches(job['acceptance'],result.get('acceptance')):
            raise SystemExit('Guest did not provide a checkpoint and acceptance evidence')
        recovery=None
        if a.recovery:
            interrupted_id=uuid.uuid4().hex
            interrupted={'id':interrupted_id,'provider':agent['provider'],'prompt':'Write DOT_RECOVERY_INTERRUPTED to dot-recovery.txt and reply done.','model':'','mode':'work','timeout':240,
                'acceptance':{'commands':[['python3','-c','import time; time.sleep(120)']]}}
            interrupted['lease']=kernel.issue(job_id=interrupted_id,agent_id=agent_id,timeout=240,mode='work',changed_bytes=4096)
            b.guest(agent,'submit',data=interrupted)
            until=time.time()+200
            while time.time()<until:
                observed=b.guest(agent,'status',interrupted_id)
                if observed.get('phase')=='acceptance':break
                if observed['status']!='running':raise SystemExit('Recovery task terminated before interruption')
                time.sleep(1)
            else:raise SystemExit('Recovery task did not reach acceptance before deadline')
            before=observed.get('checkpoint_id')
            if not before:raise SystemExit('Interrupted task has no checkpoint')
            b.guest(agent,'cancel',interrupted_id)
            until=time.time()+20
            while time.time()<until:
                stopped=b.guest(agent,'status',interrupted_id)
                if stopped['status']!='running':break
                time.sleep(1)
            if stopped['status']!='cancelled':raise SystemExit('Task did not report cancellation')
            restored=b.guest(agent,'checkpoints','restore',before)
            resumed_id=uuid.uuid4().hex
            resumed={'id':resumed_id,'provider':agent['provider'],'prompt':'Write DOT_RECOVERY_RESUMED to dot-recovery.txt and read it back.','model':'','mode':'work','timeout':120,
                'acceptance':{'files':[{'path':'dot-recovery.txt','contains':'DOT_RECOVERY_RESUMED'}]}}
            resumed['lease']=kernel.issue(job_id=resumed_id,agent_id=agent_id,timeout=120,mode='work',changed_bytes=4096)
            b.guest(agent,'submit',data=resumed)
            until=time.time()+150
            while time.time()<until:
                after=b.guest(agent,'status',resumed_id)
                if after['status']!='running':break
                time.sleep(2)
            if after['status']!='completed' or not evidence_matches(resumed['acceptance'],after.get('acceptance')):
                raise SystemExit('Resume acceptance failed')
            recovery={'status':'verified','interrupted_job':interrupted_id,'restore':restored,'resumed_job':resumed_id}
        content=run(b.ssh_command(agent,'cat','/home/dot/workspace/dot-acceptance.txt'))
        if content.strip()!='DOT_VM_ACCEPTANCE_OK':raise SystemExit('Artifact acceptance failed')
        checks.append({'agent_id':agent_id,'domain_uuid':domain_uuid,'provider':agent['provider'],'kernel_release':health['kernel_release'],
                       'inference':'verified','checkpoint_id':result['checkpoint_id'],'acceptance':result['acceptance'],'recovery':recovery,'artifact_sha256':hashlib.sha256(content.encode()).hexdigest(),'job_id':job_id})
        providers.add(agent['provider'])
status='verified' if providers=={'chatgpt','gemini'} and len(seen)>=2 else 'partial'
receipt={'status':status,'at':time.time(),'checks':checks,'both_subscription_providers_verified':providers=={'chatgpt','gemini'},'separate_vm_identity_verified':len(seen)>=2,
         'network_isolation_live_verified':False}
out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt,indent=2))
raise SystemExit(0 if status=='verified' else 1)
