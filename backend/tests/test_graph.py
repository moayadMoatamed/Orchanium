from orchanium.chem import purchasable
from orchanium.chem import rdkit_utils as rd
from orchanium.chem.critic import Species, critique
from orchanium.graph import Molecule, Reaction, RunGraph
from orchanium.models import Evidence

SMI = {
    "isobutylbenzene": "CC(C)Cc1ccccc1",
    "acetic anhydride": "CC(=O)OC(C)=O",
    "hydrogen": "[H][H]",
    "carbon monoxide": "[C-]#[O+]",
    "ibap": "CC(C)Cc1ccc(C(C)=O)cc1",
    "ibpe": "CC(C)Cc1ccc(C(C)O)cc1",
    "ibuprofen": "CC(C)Cc1ccc(C(C)C(=O)O)cc1",
    "nitrile": "CC(C#N)c1ccc(CC(C)C)cc1",
}


def _graph() -> RunGraph:
    g = RunGraph()
    for name, smi in SMI.items():
        key = rd.inchikey(smi)
        p = purchasable.check(key, smi)
        g.molecules[name] = Molecule(id=name, name=name, smiles=smi, purchasable=p.purchasable,
                                     is_target=name == "ibuprofen")
    g.molecules["ibuprofen"].purchasable = False

    def rx(rid, reactants, product, n_ev=1):
        r = Reaction(id=rid, reactants=reactants, product=product)
        r.critic = critique([Species(name=x, smiles=SMI[x]) for x in reactants],
                            Species(name=product, smiles=SMI[product]))
        r.label = "rejected" if r.critic.verdict == "block" else "literature"
        for i in range(n_ev):
            eid = f"{rid}-ev{i}"
            r.evidence.append(eid)
            g.evidence[eid] = Evidence(id=eid, agent_id="t", angle="t", query_node_id="q", source_node_id="s",
                                       reactants=reactants, products=[product], reagents=[], conditions=None,
                                       yield_pct=None, snippet="", source_url=f"https://site{i}.org/{rid}",
                                       source_title="t", source_type="web", route_name=None, step_number=None,
                                       figure_image_urls=[])
        g.reactions[rid] = r

    rx("bhc1", ["isobutylbenzene", "acetic anhydride"], "ibap", n_ev=2)
    rx("bhc2", ["ibap", "hydrogen"], "ibpe", n_ev=2)
    rx("bhc3", ["ibpe", "carbon monoxide"], "ibuprofen", n_ev=2)
    rx("nitrile_hydrolysis", ["nitrile"], "ibuprofen", n_ev=1)       # nitrile not purchasable -> gap
    rx("bogus", ["hydrogen"], "ibuprofen")                            # blocked by critic
    return g


def test_best_route_is_complete_bhc_in_order():
    g = _graph()
    routes = g.find_routes("ibuprofen")
    best = routes[0]
    assert best.complete
    assert [s.reaction_id for s in best.steps] == ["bhc1", "bhc2", "bhc3"]
    assert set(best.leaves) == {"isobutylbenzene", "acetic anhydride", "hydrogen", "carbon monoxide"}
    assert best.metrics["steps"] == 3 and best.metrics["longest_linear_sequence"] == 3


def test_partial_route_reports_gap_and_rejected_is_excluded():
    g = _graph()
    routes = g.find_routes("ibuprofen")
    ids = [[s.reaction_id for s in r.steps] for r in routes]
    assert ["nitrile_hydrolysis"] in ids
    partial = routes[ids.index(["nitrile_hydrolysis"])]
    assert not partial.complete and partial.gaps == ["nitrile"]
    assert all("bogus" not in i for i in ids)
    assert g.reactions["bogus"].label == "rejected"
