"""Content-addressed encrypted artifact records bound to a workspace and mission."""
from pydantic import BaseModel,Field
from typing import Optional

class ArtifactInput(BaseModel):
    workspace:str=Field(pattern=r'^[a-z0-9][a-z0-9-]{0,63}$')
    mission_id:Optional[str]=Field(default=None,max_length=64)
    name:str=Field(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')
    mime:str=Field(pattern=r'^(text/plain|application/json|text/markdown)$')
    content:str=Field(max_length=120_000)
