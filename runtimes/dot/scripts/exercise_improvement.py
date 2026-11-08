#!/usr/bin/env python3
"""Use the lab on a real source change; no model, VM or Chromium claims."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dot.improvement import ImprovementLab


def exercise(project, state):
    project = Path(project).resolve()
    lab = ImprovementLab(state, project)
    regression = '''import runpy,pathlib,sys
m=runpy.run_path(str(pathlib.Path(sys.argv[1])/'dot/computer.py'))
validate=m['validate_actions']
for step in ({'action':'goto','url':'https://example.com'}, {'action':'click','selector':'button'}, {'action':'read'}):
    validate({'actions':[step]})
for step in ({'action':'goto','url':'file:///etc/passwd'}, {'action':'fill','selector':'x','text':42}):
    try: validate({'actions':[step]})
    except ValueError: pass
    else: raise AssertionError('Invalid action accepted')
'''
    holdout = regression + '''
validate({'actions':[{'action':'wait','selector':'#workspace','timeout_ms':8000}]})
for step in ({'action':'wait'}, {'action':'wait','selector':'x','timeout_ms':9000}, {'action':'wait','selector':'x','timeout_ms':True}):
    try: validate({'actions':[step]})
    except ValueError: pass
    else: raise AssertionError('Unbounded or invalid wait accepted')
'''
    c = lab.create('Support bounded waits for asynchronous browser controls', ['dot/computer.py'],
        regression, holdout, scope='enterprise', tenant='itsnotai-dot', seconds=300)
    path = lab._folder(c['id']) / 'candidate/dot/computer.py'
    source = path.read_text()
    if "('goto', 'click', 'fill', 'read', 'screenshot')" not in source:
        raise ValueError('This exercise requires the original v0.3 browser baseline')
    source = source.replace("('goto', 'click', 'fill', 'read', 'screenshot')", "('goto', 'click', 'fill', 'wait', 'read', 'screenshot')")
    source = source.replace("if step['action'] in ('click', 'fill'):", "if step['action'] in ('click', 'fill', 'wait'):")
    source = source.replace("        if step['action'] == 'fill' and", "        if step['action'] == 'wait' and (type(step.get('timeout_ms', 3000)) is not int or not 1 <= step.get('timeout_ms', 3000) <= 8000):\n            raise ValueError('Wait timeout must be 1–8000 milliseconds')\n        if step['action'] == 'fill' and")
    source = source.replace("                elif action == 'read':", "                elif action == 'wait':\n                    page.locator(step['selector']).wait_for(state='visible', timeout=step.get('timeout_ms', 3000))\n                    results.append({'action': action})\n                elif action == 'read':")
    lab.edit(c['id'], 'dot/computer.py', source)
    result = lab.evaluate(c['id'])
    if result['status'] != 'verified':
        raise RuntimeError('Real source improvement failed its checks')
    promoted = lab.promote(c['id'])
    return {'schema':'dot.actual-source-improvement.v1', 'status':promoted['status'],
        'capsule_id':c['id'], 'objective':c['objective'], 'baseline_hash':c['baseline_hash'],
        'candidate_hash':promoted['candidate_hash'], 'trials':result['trials'],
        'changed_files':promoted['changes'], 'undo_checkpoint':promoted['undo_checkpoint'],
        'execution':'real local Python processes against actual project source',
        'intelligence':'assistant-authored patch; no provider inference was executed',
        'verification_scope':'browser action contract validation; not a real Chromium execution',
        'vm_boot_verified':False, 'subscription_inference_verified':False}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True)
    parser.add_argument('--state',required=True)
    parser.add_argument('--receipt',required=True)
    args=parser.parse_args()
    result=exercise(args.project,args.state)
    Path(args.receipt).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
