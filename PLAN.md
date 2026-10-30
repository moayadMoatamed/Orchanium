# Orchanium — Build Plan

> Live, literature-grounded retrosynthesis. **The LLM proposes, live literature provides evidence, and deterministic chemistry verifies.**
> Deadline: **Tue Nov 4, 9:00 PM ET**. Today: Fri Oct 30. That leaves about 5 working days, plus a buffer on Nov 4.

---

## 1. What I checked in the Meta docs (dev.meta.ai, Oct 30)

| Thing | Finding | Impact |
|---|---|---|
| Base URL / auth | `https://api.meta.ai/v1`, Bearer key. The docs call it `MODEL_API_KEY`. | We read `META_API_KEY` **or** `MODEL_API_KEY` from `.env`. |
| Text model | `muse-spark-1.3` (1M ctx; text, image, PDF in; tools, structured output, search grounding) | Main model for all agents. |
| Cheap model | `muse-spark-1.3-contributor`: **$0.10 / $0.20 per M tokens** vs $1.25 / $4.25 standard. Your data may be used for training, and it is capped at 150 RPM. | Use it for high-volume, low-stakes calls (name extraction, dedup, explanations). This **replaces the optional open-weights model**: it is just as cheap, needs no extra infra, and is still a Meta model. ⚠️ Your call: OK to send public-chemistry prompts in contributor mode? |
| Big model | `muse-wonder-1.0` ($4 / $20) | Optional. Use it only for the hardest step (gap-filling disconnections) behind a flag. |
| Responses API | `POST /v1/responses`. Structured output goes through `text.format` (not `response_format`). With `strict: true`: root object, `additionalProperties:false`, all keys required, no recursion. | Pydantic → JSON schema helper that enforces strict rules. |
| Web search | `tools: [{"type":"web_search","search_context_size":"high"}]`. Answers carry `url_citation` annotations (`url,title,start_index,end_index`). `include: ["web_search_call.results"]` returns **every source considered**, with `title, url, snippet`. Costs $2.50 / 1k queries. | Great for the Verification Chain: we get the real snippet the model saw. |
| Vision | `{"type":"input_image","image_url":"https://… or data:image/png;base64,…"}`. Max 50 images per request. | Figure reader sends crops as data URLs. |
| **SAM 3.1** | **Hosted on the same endpoint**: `model: "sam-3.1"`, a noun-phrase text prompt plus `input_image`. The output is a text grammar `<0f>N<\|box;x1..;y1..;x2..;y2..\|><\|mask;…\|>`, with `metadata.include_confidence`. Costs $2.50 / 1k images. | No Modal or GPU needed. We parse boxes ourselves (we only need boxes for cropping, not masks). |
| Unknown | Whether `web_search` + `text.format` combine in one call. Whether SAM's "chemical structure" prompt works on line drawings. | These are the first two things the smoke test checks. Fallbacks are in §7. |

**Budget sanity:** a run is about 5 researchers × (1–3 searches + about 30k tokens) plus about 40 small calls, which comes to roughly **$0.30–0.80 per run** on standard Spark. With every call cached and replay mode, $150 covers 150+ fresh runs.

---

## 2. Architecture

```
                    ┌──────────────── FastAPI ────────────────┐
 React UI ◄── SSE ──┤ /api/runs/{id}/events  (live or replay)  │
   (Vite)   ── REST ┤ /api/runs, /api/depict, /api/mol3d       │
                    └──────────────┬──────────────────────────┘
                                   │ asyncio orchestrator (per run)
   ┌──────────┐   ┌───────────────┐   ┌──────────────┐   ┌────────────┐
   │ Planner  │──►│ Researchers×N │──►│ Graph builder│──►│  Critic    │
   │ PubChem+ │   │ Spark+web_srch│   │ PubChem norm │   │ RDKit only │
   │ RDKit    │   │ ↺ intermediates│  │ dedupe/merge │   │ pass/warn/ │
   └──────────┘   └──────┬────────┘   └──────┬───────┘   │ block      │
                         ▼                   │           └─────┬──────┘
                  ┌──────────────┐           ▼                 ▼
                  │ Figure reader│     ┌───────────┐    ┌────────────┐
                  │ SAM3.1 crops │     │ Citation  │    │ Reasoner   │
                  │ → Spark vision│    │ checker   │    │ AND/OR srch│
                  │ → RDKit+PubCh│     │ (URL+quote│    │ gaps→Spark │
                  └──────────────┘     │  match)   │    │ →Critic    │
                                       └───────────┘    └─────┬──────┘
                                                              ▼
                                                        ┌──────────┐
                                                        │ Reporter │
                                                        └──────────┘
 Everything emits typed events → EventBus → (SSE fan-out + SQLite event log)
 Caches (SQLite): PubChem, LLM (hash of request), web search, HTTP fetch
```

### Event schema (designed first; the frontend builds from the event stream alone)

Envelope: `{seq, run_id, ts, kind, data}`. The `kind` values are:

| kind | data | drives |
|---|---|---|
| `run.status` | `{status, target, caps}` | header |
| `agent.status` | `{agent_id, agent_type, label, status, message}` | agent lanes |
| `agent.log` | `{agent_id, text, level}` | lane ticker |
| `prov.node` (upsert) | **`{id, parent_ids[], step_id?, node_type, status, summary, details, agent_id}`** | Verification Chain |
| `graph.molecule` (upsert) | `{id(inchikey), smiles, name, status, purchasable, depth}` | knowledge graph |
| `graph.reaction` (upsert) | `{id, reactants[], products[], reagents[], evidence_ids[], label, critic}` | knowledge graph |
| `route` | `{route_id, rank, steps[], score, label}` | route view |
| `cost` | `{llm_calls, tokens_in, tokens_out, searches, sam_images, usd}` | cost meter |
| `report` | `{markdown}` | report panel |

`node_type` ∈ `query | source | extraction | vision | resolution | check | agreement | verdict` (plus `citation`, my addition).
`status` ∈ `pending | running | pass | warn | fail`. Verdict nodes also carry `label` ∈ `literature | proposed | rejected | purchasable`.
`step_id` = the reaction id, which lets the UI group a chain per route step. Replay re-emits the same log with the original timing, scaled by a speed factor.

### Graph model
networkx `DiGraph` per run. The **Molecule** key is the InChIKey, from PubChem → RDKit. The **Reaction** key is the hash of the sorted reactant + product InChIKeys. Edges are `reactant_of` (mol→rxn) and `produces` (rxn→mol). A reaction carries `evidence[]`, `critic`, and `label`.

### Critic checks (deterministic, each one emits its own `check` prov node)
1. `parse`: every species sanitizes in RDKit.
2. `element_balance`: product heavy atoms ⊆ reactants + listed reagents, within a tolerance. Unbalanced small leaving groups (H₂O, HCl, AcOH, …) are allowed from a whitelist.
3. `product_differs`: product InChIKey ∉ reactants.
4. `conserved_core`: MCS between product and largest reactant ≥ X% of product heavy atoms. This is a cheap stand-in for atom mapping (see §7).
5. `no_cycle`: on route assembly.
6. `fg_conflicts`: SMARTS warnings (e.g. free amine + acyl chloride elsewhere, unprotected OH under Grignard).
7. `reaction_class` (bonus): SMARTS templates for ~25 named transformations (esterification, amide coupling, Friedel–Crafts acylation, reduction, Kolbe–Schmitt, …). A match adds confidence and a label.
The LLM may only write the plain-English `explanation` field. It never writes `status`.

### Reasoner
AND/OR best-first search from the target over the graph. Leaves are purchasable (curated YAML, ~200 InChIKeys, plus heuristics such as heavy atoms ≤ 8 with no stereo). Score = evidence count, minus step penalty, minus warnings. Gaps (a non-purchasable leaf with no producing reaction) → Spark proposes ≤ 3 disconnections as **names** → PubChem → Critic → accepted proposals enter as `proposed`. Max depth 6.

---

## 3. My changes and additions to the brief (and why)

1. **Citation checker agent (new, deterministic).** For every evidence record: fetch the URL (cached), check that it resolves, and fuzzy-match the snippet and the reactant/product names against the page text. This adds a `citation` node to the chain (✓ resolves, ✓ quote found). It turns "has a citation" into "the citation demonstrably says this", the strongest anti-hallucination signal we can show judges, and it costs nothing.
2. **Contributor-mode Spark instead of a 3rd-party open-weights host**: same price class, zero extra infra (needs your OK, see above).
3. **Two-pass research.** Pass A is Spark + web_search with free-text cited answers and `web_search_call.results`. Pass B is a structured extraction over pass A's text plus snippets (strict JSON schema). This works whether or not tools and `text.format` combine in one call, and it gives clean provenance: query → sources → extracted claim.
4. **MCS "conserved core" check instead of rxnmapper by default.** rxnmapper drags in torch and old transformers pins (installation is painful on Windows and Docker). It stays an optional extra if time permits.
5. **Figure round-trip check (vision used twice).** After a crop is read into SMILES, RDKit re-renders it and Spark vision compares the rendering with the original crop ("same molecule?"). The deterministic part is the PubChem/RDKit agreement. The visual check is shown as a separate, clearly labelled signal.
6. **React Flow + ELK for both the chain and the knowledge graph**: one rendering stack and one token file, so the same node visuals appear everywhere. ELK's layered layout gives a readable retrosynthesis tree with smooth position tweening, where force layouts jitter.
7. **Run timeline scrubber**: replay can be dragged to any point in time. It is great for the 2-minute video and comes nearly free, because the UI is a pure function of the event log.
8. **Green-chemistry metrics per route** (atom economy, step count, longest linear sequence), computed by RDKit. Cheap, deterministic, and judges like it.
9. **Where figures come from:** figure reading targets open sources where we can reliably pull scheme images (Google Patents `patentimages`, PMC/Europe PMC figures, orgsyn.org, Wikipedia/Commons). Paywalled publisher pages are skipped and shown as "figure unavailable".

---

## 4. File layout

```
Orchanium_Ultra/
├─ PLAN.md  README.md  docker-compose.yml  .env.example
├─ backend/
│  ├─ pyproject.toml / requirements.txt   Dockerfile
│  ├─ orchanium/
│  │  ├─ main.py               FastAPI app, SSE, REST
│  │  ├─ config.py             settings, caps, model ids
│  │  ├─ events.py             event schema (pydantic) + EventBus
│  │  ├─ store.py              SQLite: runs, events, caches
│  │  ├─ orchestrator.py       run lifecycle, parallelism, caps
│  │  ├─ meta/
│  │  │  ├─ client.py          Responses API wrapper (cache, cost, retries, strict schema)
│  │  │  └─ sam.py             SAM 3.1 call + output-grammar parser
│  │  ├─ chem/
│  │  │  ├─ pubchem.py         name→structure (cached, rate-limited)
│  │  │  ├─ rdkit_utils.py     canon, inchikey, depict SVG, 3D molblock, FG scan
│  │  │  ├─ critic.py          deterministic checks
│  │  │  ├─ templates.py       reaction-class SMARTS
│  │  │  └─ purchasable.py + data/building_blocks.yaml
│  │  ├─ agents/  planner.py researcher.py figure_reader.py graph_builder.py
│  │  │           citation_checker.py reasoner.py reporter.py
│  │  └─ graph.py              networkx model + route search
│  ├─ prompts/                 planner.md researcher_search.md researcher_extract.md
│  │                           figure_read.md gap_proposer.md reporter.md explain_verdict.md
│  └─ tests/                   test_critic.py test_normalize.py test_sam_parser.py
├─ frontend/  (Vite + React + TS + Tailwind + @xyflow/react + elkjs + 3Dmol)
│  └─ src/
│     ├─ tokens.ts             ALL colors/icons per node type, status, verdict
│     ├─ state/runStore.ts     zustand reducer: events → UI state (live == replay)
│     ├─ api/sse.ts
│     └─ components/ AgentLanes, VerificationChain, KnowledgeGraph, RouteView,
│                    NodeDetailPanel, Mol2D, Mol3D, ReportPanel, CostMeter,
│                    Legend, Timeline, Filters
└─ scripts/  smoke_meta.py  smoke_chem.py  eval.py  record_demo.py
```

---

## 5. Milestones → days

| Day | Date | Goal | Done when |
|---|---|---|---|
| D1 | **Fri Oct 30** | Smoke tests (Meta text, web_search, structured output, vision, SAM; RDKit; PubChem). Event schema, store, Meta client, PubChem/RDKit layer, Critic, plus tests | `pytest` green; `smoke_meta.py` prints all ✓ |
| D2 | Sat Oct 31 | **Vertical slice (CLI)**: aspirin → planner → 1 researcher → graph → critic → citation check → reasoner → reporter. Event log in SQLite; replay works | `python -m orchanium.cli run aspirin` prints a cited, critic-checked route. **Commit.** |
| D3 | Sun Nov 1 | Parallel researchers plus intermediate follow-ups. FastAPI SSE. Frontend shell: tokens, agent lanes, **Verification Chain v1**, knowledge graph, route view | Aspirin and paracetamol build live in the browser. **Commit.** |
| D4 | Mon Nov 2 | Figure reader (SAM + vision + round-trip). Reasoner gap proposals (`proposed` label). Node detail panel, 2D/3D viewers, report panel, cost meter | Ibuprofen shows both routes; at least one figure read appears in a chain. **Commit.** |
| D5 | Tue Nov 3 | Chain polish (edge flow animation, filters, collapse checks, PNG/SVG export), timeline scrubber, `eval.py` on 4 targets, README + diagram, Docker Compose | Eval table in README; `docker compose up` works. **Commit.** |
| D6 | Wed Nov 4 | Buffer, record replay runs, demo script and video, submit **before 9 PM ET** | Submitted |

**Cut line if behind** (drop in this order): Muse Wonder flag → timeline scrubber → round-trip vision check → green metrics → 3D viewer → figure reader (the chain still has every other node type). Never cut: live chain, critic, citations, replay.

---

## 6. Feasibility notes (telling you early)

- **Figure reader is the riskiest piece.** SAM's text-prompted segmentation is trained on natural images, so "chemical structure" on line art may return poor boxes. Fallback, in order: (a) try several prompts ("molecule drawing", "diagram"); (b) use SAM box/point prompts seeded from a coarse Spark-vision layout pass; (c) use connected-component cropping (OpenCV) + Spark vision, and SAM refines. SAM keeps a real job in every variant, but I'll tell you if it ends up as weak as (c).
- **Literature access**: web_search returns pages, not full PDFs. Most evidence will be snippet-level from Wikipedia, patents, Org. Synth., PMC, and Chemistry LibreTexts. That is honest and enough for the 4 eval targets.
- **Python**: you have 3.13 locally. RDKit has 3.13 wheels, so local dev uses a venv on 3.13 and Docker uses 3.11 as specified.
- **rxnmapper**: optional only (see §3.4).

---

## 7. Fallbacks for API unknowns
- If `web_search` + `text.format` can't combine, use the two-pass approach (already the default).
- If `web_search_call.results` is missing, take sources from `url_citation` annotations only.
- If a research call is slow (>60 s), apply a per-agent timeout. The UI shows the agent as `failed` and the run continues.
