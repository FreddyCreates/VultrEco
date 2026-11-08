"""Workspace-scoped encrypted memory records with explicit provenance."""
import uuid
from pydantic import BaseModel, Field

class MemoryInput(BaseModel):
    workspace:str=Field(pattern=r'^[a-z0-9][a-z0-9_-]{1,39}$')
    label:str=Field(min_length=1,max_length=120)
    content:str=Field(min_length=1,max_length=16000)
    origin:str=Field(default='operator',max_length=120)

class WorkspaceInput(BaseModel):
    slug:str=Field(pattern=r'^[a-z0-9][a-z0-9_-]{1,39}$')
    description:str=Field(default='',max_length=500)

# Multi-user isolation is NOT supported: all data is owned by the single API administrator.
