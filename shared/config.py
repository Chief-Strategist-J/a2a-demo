"""Config loader: reads config.yaml, interpolates ${VAR:default} env vars,
and returns typed Pydantic models."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def _interpolate(value: Any) -> Any:
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(2) or "")
        return _ENV_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(i) for i in value]
    return value


def _load_raw(path: str | Path) -> dict:
    with open(path) as f:
        return _interpolate(yaml.safe_load(f))


# ---------- typed models ----------

class ModelCfg(BaseModel):
    provider: str
    model_id: str
    temperature: float = 0.1
    max_tokens: int = 1024


class NodeCfg(BaseModel):
    id: str
    type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class FlowCfg(BaseModel):
    entry: str
    nodes: List[NodeCfg]
    edges: List[List[str]]


class ToolCfg(BaseModel):
    name: str
    enabled: bool = False
    description: str = ""


class SkillCfg(BaseModel):
    id: str
    name: str
    description: str
    input_modes: List[str] = ["text"]
    output_modes: List[str] = ["text"]


class AgentCfg(BaseModel):
    name: str
    description: str
    port: int
    public_url: str
    model: ModelCfg
    flow: FlowCfg
    tools: List[ToolCfg] = Field(default_factory=list)
    skills: List[SkillCfg] = Field(default_factory=list)


class EndpointCfg(BaseModel):
    url: str


class AuthCfg(BaseModel):
    enabled: bool = True
    tokens: Dict[str, str] = Field(default_factory=dict)


class StreamingCfg(BaseModel):
    enabled: bool = True


class AppCfg(BaseModel):
    agents: Dict[str, AgentCfg]
    agent_endpoints: Dict[str, EndpointCfg] = Field(default_factory=dict)
    auth: AuthCfg = Field(default_factory=AuthCfg)
    streaming: StreamingCfg = Field(default_factory=StreamingCfg)
    providers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


def load(path: str | Path = "config.yaml") -> AppCfg:
    return AppCfg(**_load_raw(path))
