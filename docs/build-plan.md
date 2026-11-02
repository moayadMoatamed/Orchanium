# Orchanium: Build Plan (v2)

> **Can this new molecule be made, and how?** Orchanium collects *clues* from published chemistry, connects them in a verified knowledge graph, and has two Meta-model agents debate over that graph. The output is a route and a feasibility verdict, and every claim traces back to evidence.
>
> **The LLM proposes and argues, literature provides clues, deterministic chemistry verifies.**
>
> Deadline: **Tue Nov 4, 9:00 PM ET**.

v1 of this plan (re-finding routes for known drugs) is in git history. v2 targets **new compounds**, and known drugs are used only as tests in **blind mode** (see §6).

---

## 1. Design principles

1. **One shape per concept.** Every source produces the same `Clue`. Every molecule goes through one `Resolver`. Every precedent is scored by one function. Every agent uses the same graph tools. New sources plug in and need no special cases.
2. **Structures never come from the LLM.** Names go to PubChem, then OPSIN. Cuts come from RDKit templates. SMILES come from databases. The LLM chooses, argues and explains.
3. **Verdicts are computed, not voted.** Agents debate, but per-step evidence grades and the final feasibility label come from deterministic rules over the graph and the critic.
4. **Everything is an event.** The UI, the Verification Chain and replay are all built from the event stream.

---

## 2. Pipeline

```
 target (SMILES / name / drawing)
   │
 ① DECOMPOSE (code)       reaction-class registry run in reverse (RDKit)
   │                      → hypothesis tree: target ⇐ precursors ⇐ … ⇐ buyable
   │                      every cut is a Hypothesis reaction in the graph
   │
 ② GATHER CLUES           one ResearchNeed per hypothesis step:
   │  (ClueSources,        "reactions of class C making things like P from things like R"
   │   parallel)          ├─ USPTO index      1.8M patent reactions, structure similarity (code)
   │                      ├─ Web researcher   Muse Spark + web_search → clues with conditions
   │                      ├─ Europe PMC       open-access full text → Spark extracts clues
   │                      └─ PubChem          nearest known analogs of query molecules
   │                      all return Clue → Resolver → graph
   │
 ③ KNOWLEDGE GRAPH        Molecule · Reaction(hypothesis | observed) · Clue · Source
   │                      edges: reactant_of, produces, evidence_for, similar_to (Tanimoto),
   │                             precedent_for (observed → hypothesis, scored)
   │                      Critic (RDKit) + Citation checker annotate every reaction / clue
   │
 ④ DEBATE (Muse Spark ×2, function-calling over graph tools)
   │   🔨 Builder:  proposes a route, cites precedent nodes per step
   │   🔍 Skeptic:  hunts weak steps, negative clues, poor analogies; can request research
   │   2–3 rounds · cited node ids are validated by code · critic is referee
   │
 ⑤ VERDICT (code) + REPORT (Spark)
      per step:  direct precedent | analog precedent (score) | no precedent | blocked
      overall:   Feasible | Plausible | Uncertain | Unlikely  (deterministic rule)
```

### Core data shapes
- **`MolRef`** — `{name?, smiles?}` → `Resolver.resolve()` → `Molecule{inchikey, smiles, name, source: pubchem|opsin|smiles}`.
- **`Clue`** — one observed reaction: reactants/products/reagents (`MolRef`), conditions `{temperature_c, time, solvent, catalyst, text}`, yield, **outcome (success | failure)**, source `{kind, url, title, snippet}`, `origin` (which ClueSource).
- **`ResearchNeed`** — `{hypothesis_id, product, reactants, reaction_class}`. It is the only input a ClueSource receives.
- **`precedent_score(observed, hypothesis)`** — class match + product similarity + reactant similarity → 0–1 (one function).

### Graph tools (shared by both debate agents)
`overview()` · `get_node(id)` · `neighbors(id, edge?)` · `precedents(hypothesis_id)` · `find(kind, filter)` · `check_step(hypothesis_id)` · `request_research(node_id, question)`. Agent prompts explain the schema and a traversal strategy (target → hypotheses → precedents → clues → sources).

### Evidence grades and feasibility rule
- Step grade: **direct** (clue with the exact molecules), **analog** (best precedent score ≥ 0.55), **weak** (≥ 0.35), **none**, **blocked** (critic fail).
- Route: **Feasible** = all steps direct or analog, and no unresolved Skeptic objection backed by a failure clue. **Plausible** = at most one weak step. **Uncertain** = any none step. **Unlikely** = a blocked step, or a sustained failure-clue objection.

---

## 3. Free data sources (verified Oct 30)

| Source | Key? | Use |
|---|---|---|
| Meta Model API (Spark, Wonder, SAM 3.1) | yours | research, extraction, debate, figure reading |
| USPTO reactions 1976–2016 (Figshare, CC0) | none, local ~163 MB | structure-similarity precedents with patent citations |
| PubChem PUG REST | none | names → structures, similarity search for analogs |
| OPSIN (EBI web service) | none | systematic names of never-made molecules |
| Europe PMC REST | none | open-access full-text experimental sections |
| OpenAlex | free key (since Feb 2026) | optional, later |

---

## 4. Reuse from v1
Kept as-is: Meta client (cache, cost, caps), SAM wrapper, PubChem + RDKit utilities, critic checks, purchasability, citation checker, event bus, store, and replay. The researcher becomes the Web ClueSource. The graph builder and reasoner are replaced by graph v2, the debate and the verdict.

---

## 5. Schedule

| Day | Goal |
|---|---|
| **Fri Oct 30** | v1 vertical slice ✅. v2: class registry + decomposer, USPTO index, clue model, graph v2 |
| **Sat Oct 31** | Clue sources (USPTO, web, PubChem analogs), graph tools, debate + verdict, blind ibuprofen end to end (CLI) |
| **Sun Nov 1** | FastAPI + SSE, frontend shell, **Verification Chain**, live graph, debate panel |
| **Mon Nov 2** | Europe PMC source, figure reader (SAM), route view, report, cost meter, replay |
| **Tue Nov 3** | Blind-mode eval (4 targets + 1 truly novel molecule), README, Docker, polish |
| **Wed Nov 4** | Buffer, demo video, submit before 9 PM ET |

**Cut order if late:** 3D viewer → Europe PMC → figure reader → timeline scrubber.
**Never cut:** decomposer, clues, graph, debate, verdict, Verification Chain, replay.

---

## 6. Evaluation: blind mode
For a known drug, `blind=True` drops every clue that contains the target molecule or names it, so Orchanium must reason from analogs alone. Success means it recovers a published route (or a critic-valid alternative) and rates it Feasible or Plausible. Targets: paracetamol, ibuprofen, sildenafil, and one truly novel analog (no PubChem entry) as the showcase.
