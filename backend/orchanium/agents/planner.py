"""Planner: turns the user's input (SMILES or name, known or never made) into
a verified target structure via the Resolver, and inspects it with RDKit."""
from __future__ import annotations

from ..chem import rdkit_utils as rd
from ..chem.resolver import MolRef, resolve
from ..context import RunContext
from ..events import ProvNode
from ..models import TargetInfo

AGENT_ID = "planner"


async def run(ctx: RunContext, query: str) -> TargetInfo:
    q = query.strip()
    looks_like_smiles = " " not in q and rd.parse(q) is not None and any(ch in q for ch in "=()[]#@1234")
    res = await resolve(MolRef(smiles=q) if looks_like_smiles else MolRef(name=q))
    if not res.ok:
        raise ValueError(f"could not resolve the target '{q}': {res.error}")
    target = TargetInfo(query=q, name=res.name if res.known or not looks_like_smiles else "Target",
                        smiles=res.smiles, inchikey=res.inchikey, cid=res.cid, known=res.known,
                        description=rd.describe(res.smiles))
    ctx.target = target
    d = target.description
    ctx.log(AGENT_ID, f"Target: {target.name} ({d['formula']}); "
                      + (f"known compound, PubChem CID {target.cid}" if target.known else "NOT in PubChem: a new compound"))
    ctx.prov(ProvNode(id="target", node_type="resolution", status="pass", agent_id=AGENT_ID,
                      summary=f"{target.name}: {d['formula']}, {'PubChem CID ' + str(target.cid) if target.known else 'new compound'}",
                      details={"query": q, "smiles": target.smiles, "inchikey": target.inchikey, "cid": target.cid,
                               "method": res.method, "structure": d}))
    return target
