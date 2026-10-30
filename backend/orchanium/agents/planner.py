"""Planner: resolves the target via PubChem (never via the LLM), inspects it
with RDKit, and asks Muse Spark for complementary research angles."""
from __future__ import annotations

from ..chem import pubchem
from ..chem import rdkit_utils as rd
from ..context import RunContext, prompt
from ..events import ProvNode
from ..models import ResearchPlan, TargetInfo

AGENT_ID = "planner"


async def resolve_target(ctx: RunContext, query: str) -> TargetInfo:
    """Accepts a name or a SMILES string."""
    q = query.strip()
    looks_like_smiles = " " not in q and any(ch in q for ch in "=()[]#@")
    if not looks_like_smiles:
        res = await pubchem.resolve(q)
        if res.ok:
            return TargetInfo(query=q, name=res.title or q, smiles=res.smiles, inchikey=res.inchikey,
                              cid=res.cid, description=rd.describe(res.smiles))
    mol = rd.parse(q) if " " not in q else None
    if mol is None:
        raise ValueError(f"Could not resolve '{q}' as a PubChem name or a valid SMILES")
    smiles, key = rd.Chem.MolToSmiles(mol), rd.inchikey(mol)
    hit = await pubchem.lookup_inchikey(key) or {}
    return TargetInfo(query=q, name=hit.get("Title") or q, smiles=smiles, inchikey=key, cid=hit.get("CID"),
                      description=rd.describe(smiles))


async def run(ctx: RunContext, query: str, n_angles: int) -> tuple[TargetInfo, ResearchPlan]:
    target = await resolve_target(ctx, query)
    ctx.target = target
    d = target.description
    ctx.log(AGENT_ID, f"Target resolved via PubChem: {target.name} ({d['formula']}, CID {target.cid})")
    ctx.prov(ProvNode(
        id="target", node_type="resolution", status="pass", agent_id=AGENT_ID,
        summary=f"{target.name} → PubChem CID {target.cid}",
        details={"query": query, "smiles": target.smiles, "inchikey": target.inchikey, "cid": target.cid,
                 "structure": d, "method": "PubChem PUG REST name lookup → RDKit canonicalisation"},
    ))
    fgs = ", ".join(f"{k}×{v}" for k, v in d["functional_groups"].items()) or "none detected"
    resp = await ctx.client.respond(
        prompt("planner", name=target.name, smiles=target.smiles, formula=d["formula"], mw=d["mw"],
               rings=d["rings"], aromatic_rings=d["aromatic_rings"], stereocenters=d["stereocenters"],
               functional_groups=fgs, n_angles=n_angles),
        schema=ResearchPlan, effort="low",
    )
    plan: ResearchPlan = resp.parsed
    plan.angles = plan.angles[:n_angles]
    ctx.log(AGENT_ID, "Research plan: " + " | ".join(a.title for a in plan.angles))
    return target, plan
