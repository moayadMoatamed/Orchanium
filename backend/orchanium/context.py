"""Per-run context shared by all agents: event bus, Meta client, graph, and
helpers that keep agent status / provenance emission uniform."""
from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from .config import PROMPTS
from .events import AgentStatus, EventBus, ProvNode
from .meta.client import MetaClient


def short_id(prefix: str, *parts: Any) -> str:
    h = hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]
    return f"{prefix}:{h}"


def prompt(template: str, **kwargs: Any) -> str:
    """Load backend/prompts/<name>.md and fill {placeholders}."""
    text = (PROMPTS / f"{template}.md").read_text(encoding="utf-8")
    for k, v in kwargs.items():
        text = text.replace("{" + k + "}", str(v))
    return text


@dataclass
class RunContext:
    run_id: str
    bus: EventBus
    client: MetaClient
    target: Any = None                               # TargetInfo once planned
    blind: bool = False                              # hide clues that contain/name the target
    prov_nodes: dict[str, ProvNode] = field(default_factory=dict)

    def prov(self, node: ProvNode) -> ProvNode:
        """Upsert a provenance node; parent_ids are merged, never dropped."""
        old = self.prov_nodes.get(node.id)
        if old:
            node.parent_ids = list(dict.fromkeys(old.parent_ids + node.parent_ids))
            node.details = {**old.details, **node.details}
            node.step_id = node.step_id or old.step_id
            node.agent_id = node.agent_id or old.agent_id
        self.prov_nodes[node.id] = node
        self.bus.prov(node)
        return node

    def log(self, agent_id: str, text: str, level: str = "info") -> None:
        self.bus.log(agent_id, text, level)

    def agent_status(self, agent_id: str, agent_type: str, label: str, status: str, message: str = "") -> None:
        self.bus.publish("agent.status", AgentStatus(agent_id=agent_id, agent_type=agent_type,
                                                     label=label, status=status, message=message))

    @asynccontextmanager
    async def agent(self, agent_id: str, agent_type: str, label: str):
        """Marks the agent running/done/failed. Failures are reported and
        swallowed so the run continues (graceful degradation)."""
        self.agent_status(agent_id, agent_type, label, "running")
        holder: dict[str, Any] = {"message": "", "failed": False}
        try:
            yield holder
        except Exception as e:  # noqa: BLE001
            holder["failed"] = True
            self.log(agent_id, f"{type(e).__name__}: {e}", "error")
            self.agent_status(agent_id, agent_type, label, "failed", str(e)[:200])
            return
        self.agent_status(agent_id, agent_type, label, "done", holder.get("message", ""))
