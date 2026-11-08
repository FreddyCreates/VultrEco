#!/usr/bin/env python3
"""Upgrade a stopped guest after disk/UUID verification, retaining the original disk backup."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dot.core import load_config
from dot.vm import Libvirt


def upgrade(config_path,agent_id):
    config=load_config(config_path);backend=Libvirt(config)
    with sqlite3.connect(Path(config['state_dir'])/'dot.sqlite3') as db:
        row=db.execute('SELECT data FROM agents WHERE id=?',(agent_id,)).fetchone()
        if not row:raise ValueError('Unknown agent')
        agent=json.loads(row[0])
        jobs=[json.loads(r[0]) for r in db.execute('SELECT data FROM jobs WHERE agent_id=?',(agent_id,))]
    if any(j['status'] not in ('completed','failed','cancelled','lost') for j in jobs):raise ValueError('Resolve active jobs before upgrading')
    observed=backend.inspect(agent)
    if observed['power_state']!='shut off':raise ValueError('Shut down the VM completely before upgrading')
    disk=backend.paths(agent)/'disk.qcow2'
    backup=disk.with_name('disk.before-0.4-'+str(time.time_ns())+'.qcow2')
    shutil.copy2(disk,backup)
    argv=['virt-customize','-a',str(disk)]
    source=Path(__file__).resolve().parents[1]/'dot'
    for name in ('guest.py','checkpoint.py','verification.py','computer.py','delegation.py','improvement.py'):
        argv += ['--upload',str(source/name)+':/opt/dot/'+name,'--chmod','0644:/opt/dot/'+name]
    subprocess.run(argv,check=True)
    result={'agent_id':agent_id,'status':'guest_source_upgraded','disk_backup':str(backup),'protocol_version':'0.3','boot_verified':False}
    backend.paths(agent).joinpath('upgrade-0.4.json').write_text(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',default='config.json');p.add_argument('--agent',required=True);a=p.parse_args()
    print(json.dumps(upgrade(a.config,a.agent),indent=2))
