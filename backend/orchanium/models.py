"""Pydantic models for agent I/O. Classes used as LLM structured-output schemas
are marked; their fields must stay within the Meta strict-schema subset."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["patent", "paper", "procedure", "textbook", "encyclopedia", "web"]


# ---------------------------------------------------------------- planner

class ResearchAngle(BaseModel):          # LLM schema
    title: str = Field(description="Short label, e.g. 'Industrial process routes'")
    focus: str = Field(description="What this researcher should look for")
    query_hint: str = Field(description="A good first web search query")


class ResearchPlan(BaseModel):           # LLM schema
    angles: list[ResearchAngle]
    rationale: str


class TargetInfo(BaseModel):
    query: str
    name: str
    smiles: str
    inchikey: str
    cid: int | None = None
    description: dict = Field(default_factory=dict)


# ---------------------------------------------------------------- researcher

class EvidenceStepLLM(BaseModel):        # LLM schema
    reactants: list[str] = Field(description="Chemical NAMES of the reactants (never SMILES)")
    products: list[str] = Field(description="Chemical NAMES of products; main product first")
    reagents: list[str] = Field(description="Names of reagents, catalysts and solvents")
    conditions: str | None = Field(description="Temperature, time, atmosphere etc., if stated")
    yield_pct: float | None = Field(description="Reported yield in percent, if stated")
    snippet: str = Field(description="Short verbatim sentence from the source describing this step (<= 300 chars)")
    source_url: str = Field(description="URL of the source page this step came from (from your search results)")
    source_title: str
    source_type: SourceType
    route_name: str | None = Field(description="Name of the overall route, e.g. 'BHC process', if any")
    step_number: int | None = Field(description="Position of this step within its route, if known")
    figure_image_urls: list[str] = Field(description="Direct URLs of reaction-scheme images on the source page, if seen")


class ResearchFindings(BaseModel):       # LLM schema
    steps: list[EvidenceStepLLM]
    intermediates_to_research: list[str] = Field(
        description="Names of intermediates whose own synthesis is not covered yet")
    notes: str


class Evidence(EvidenceStepLLM):
    id: str
    agent_id: str
    angle: str
    query_node_id: str
    source_node_id: str
    url_in_search_results: bool = False


# ---------------------------------------------------------------- reasoner / report

class RouteStep(BaseModel):
    reaction_id: str
    product: str
    reactants: list[str]
    label: Literal["literature", "proposed", "rejected"]
    critic: str
    evidence_ids: list[str]


class Route(BaseModel):
    route_id: str
    rank: int
    steps: list[RouteStep]                # starting materials -> target
    score: float
    complete: bool
    leaves: list[str]
    gaps: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
