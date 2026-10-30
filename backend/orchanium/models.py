"""Shared data shapes. Classes marked `LLM schema` are sent to Muse Spark as
strict structured-output schemas, so they stay within the strict subset."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .chem.resolver import MolRef

SourceKind = Literal["patent", "paper", "procedure", "textbook", "encyclopedia", "web", "database", "vendor"]


# ---------------------------------------------------------------- clues (any source)

class Conditions(BaseModel):
    temperature_c: float | None = None
    time: str | None = None
    solvent: str | None = None
    catalyst: str | None = None
    text: str | None = None


class SourceRef(BaseModel):
    kind: SourceKind
    title: str
    url: str | None = None
    snippet: str | None = None           # verbatim text from the source, if any
    citation: str | None = None          # e.g. patent number, DOI


class Clue(BaseModel):
    """One observed reaction from any source. Every ClueSource emits this shape."""
    id: str
    origin: str                          # name of the ClueSource
    need_id: str | None = None           # hypothesis this clue was gathered for
    reactants: list[MolRef]
    products: list[MolRef]               # main product first
    reagents: list[MolRef] = Field(default_factory=list)
    conditions: Conditions = Field(default_factory=Conditions)
    yield_pct: float | None = None
    outcome: Literal["success", "failure"] = "success"
    source: SourceRef


class ResearchNeed(BaseModel):
    """What to look for: reactions like `hypothesis` (product from reactants)."""
    id: str                              # hypothesis reaction id
    product_smiles: str
    product_name: str
    reactant_smiles: list[str]
    reactant_names: list[str]
    reaction_class: str | None
    analog_names: list[str] = Field(default_factory=list)   # known molecules similar to the product
    focus: str | None = None                                # a specific question to investigate


# ---------------------------------------------------------------- web researcher (LLM schema)

class ClueLLM(BaseModel):
    reactants: list[str] = Field(description="Chemical NAMES of reactants (never SMILES)")
    products: list[str] = Field(description="Chemical NAMES of products, main product first")
    reagents: list[str] = Field(description="Names of reagents, catalysts and solvents")
    temperature_c: float | None = Field(description="Reaction temperature in °C if stated")
    time: str | None = Field(description="Reaction time if stated, e.g. '4 h'")
    solvent: str | None
    catalyst: str | None
    conditions_text: str | None = Field(description="Other conditions as stated")
    yield_pct: float | None = Field(description="Reported yield in percent if stated")
    outcome: Literal["success", "failure"] = Field(
        description="'failure' if the source reports the reaction did not work or gave the wrong product")
    snippet: str = Field(description="Short sentence copied verbatim from the source stating this reaction")
    source_url: str = Field(description="Exact URL of the page from your search results")
    source_title: str
    source_type: Literal["patent", "paper", "procedure", "textbook", "encyclopedia", "web"]


class ClueFindings(BaseModel):
    clues: list[ClueLLM]
    notes: str


# ---------------------------------------------------------------- target

class TargetInfo(BaseModel):
    query: str
    name: str
    smiles: str
    inchikey: str
    cid: int | None = None
    known: bool = False                  # has a PubChem record
    vendors: int = 0                     # suppliers listing it in PubChem (>0 = it has been made)
    description: dict = Field(default_factory=dict)
