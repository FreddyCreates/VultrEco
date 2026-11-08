"""NEXUS protocol ingress (local adapter). No external NEXUS runtime is implied."""
from pydantic import BaseModel, Field
from typing import Literal

class Budget(BaseModel):
    seconds:int=Field(ge=1,le=18)
    cpu:float=Field(gt=0,le=.5)
    memory_mb:int=Field(ge=16,le=192)
    max_children:int=Field(default=0,ge=0,le=0)
    spend_usdc:float=Field(default=0.0,ge=0,le=0)

class NexusTask(BaseModel):
    protocol:Literal['nexus.task.v1']
    correlation_id:str=Field(min_length=8,max_length=128)
    tenant:Literal['single-admin']
    principal:Literal['operator']
    workspace:str=Field(pattern=r'^[a-z0-9][a-z0-9-]{0,63}$')
    action:Literal['execute.python','execute.browser']
    title:str=Field(min_length=3,max_length=100)
    code:str=Field(default='',max_length=16000)
    url:str=Field(default='',max_length=300)
    selector:str=Field(default='',max_length=200)
    budget:Budget
    approval:str=Field(default='not-required-for-code-only',max_length=100)

def compile_handoff(task:NexusTask,mission:dict):
    return {'protocol':'nexus.handoff.v1','correlation_id':task.correlation_id,'tenant':task.tenant,'principal':task.principal,'workspace':task.workspace,
            'authority':{'financial_spend':False,'subagents':0,'cross_workspace':False},
            'mission_id':mission['id'],'mission_status':mission['status'],'receipt':mission['receipt'],
            'verified_external_runtime':False,'adapter':'local-contract-to-capsula-mission'}
