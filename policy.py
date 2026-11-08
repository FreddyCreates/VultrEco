"""Bounded mission policy: explicit authority grants, no inherited financial authority."""
from dataclasses import dataclass

CAPABILITIES={
 'python':{'implemented':True,'isolation':'docker','network':'none','writes':'disposable'},
 'browser':{'implemented':False,'isolation':'playwright-worker-required','network':'allowlisted-only'},
 'research':{'implemented':False,'isolation':'research-worker-required','network':'allowlisted-only'},
 'loom':{'implemented':False,'isolation':'remote-worker-required','network':'policy-defined'},
 'pocket-agent':{'implemented':False,'isolation':'recursive-harness-required','network':'policy-defined'},
 'wallet':{'implemented':False,'authority':'user-signature-or-delegation','custody':'none'},
 'payments':{'implemented':False,'authority':'explicit-user-approved-spend','custody':'none'},
}
MAX_CPU=.5;MAX_MEMORY_MB=192;MAX_SECONDS=18

def evaluate(mission,backend_ready):
    reasons=[]
    if mission.kind not in CAPABILITIES:reasons.append('unknown capability')
    elif not CAPABILITIES[mission.kind]['implemented'] and (mission.kind!='browser' or not backend_ready):reasons.append('execution adapter not activated')
    if mission.kind=='python' and not mission.code.strip():reasons.append('python code required')
    if mission.kind=='python' and not backend_ready:reasons.append('isolated runtime unavailable')
    if mission.kind=='browser' and not getattr(mission,'url','').startswith('https://'):reasons.append('HTTPS browser target required')
    return {'protocol':'capsula.policy.v2','decision':'deny' if reasons else 'permit',
     'reasons':reasons,'runtime':'isolated-worker' if backend_ready and mission.kind!='python' else ('docker-or-worker' if mission.kind=='python' else 'unavailable'),
     'authority':{'task_only':True,'financial_spend':False,'cross_workspace':False,'subagents':0},
     'limits':{'seconds':MAX_SECONDS,'cpu':MAX_CPU,'memory_mb':MAX_MEMORY_MB,'network':'none','privileged':False}}
