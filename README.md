# Orchanium

**Can this molecule be made, and how?**

Orchanium answers that question for compounds that may never have been made before. It cuts a
target apart with real chemistry rules, hunts published literature for *clues* — "this material
reacted with that one, this way, at this temperature" — connects the clues into a knowledge graph,
and then has two Meta-model agents argue over that graph until a verdict holds up.

The division of labour is the whole design:

> **The model proposes and argues. The literature provides the clues. Deterministic chemistry
> decides.**

The model never invents a structure, never scores its own evidence, and never picks the final
label. A fixed rule over the graph does that.

Built for the Meta Global AI Developer Hackathon, on the Meta Model API (Muse Spark for reasoning
and tool use, SAM 3.1 for reading structures out of figures).

---

## What it looks like

Four views, each a pure reduction of one event stream, so any run can be replayed from its log:

| View | What it shows |
|---|---|
| **Result** | The answer in one sentence, the verdict, every step with its real conditions and evidence strength, what to buy, what to test first |
| **Graph** | The knowledge graph assembling itself live. Nodes are told apart by shape, not colour; the chosen route is highlighted |
| **Verification** | For any step: sources → reported reaction → citation check → structures → precedent match → chemistry checks → verdict |
| **Debate** | The Builder/Skeptic exchange, with each cited node shown — and citations that did not check out struck through |

---

## How it works

```
         target: a name, a SMILES, or a drawing
                          │
  ┌───────────────────────▼───────────────────────────────────────────────┐
  │ ① DECOMPOSE                                                   (code) │
  │   A registry of reaction classes, run in reverse with RDKit, cuts    │
  │   the target into precursors, and those into theirs, best-first      │
  │   until every leaf is buyable. Each cut is a *hypothesis* reaction.  │
  └───────────────────────┬───────────────────────────────────────────────┘
                          │  one research need per hypothesis step
  ┌───────────────────────▼───────────────────────────────────────────────┐
  │ ② GATHER CLUES                                      (parallel)       │
  │   USPTO index   1.45M patent reactions, searched by structure        │
  │   Web research  Muse Spark + built-in web_search → conditions,       │
  │                 yields, and crucially *failures*                     │
  │   PubChem       names → structures, nearest known analogues          │
  │   SAM 3.1       reaction schemes read out of figures                 │
  │   Every source emits the same `Clue`. New sources need no new code.  │
  └───────────────────────┬───────────────────────────────────────────────┘
  ┌───────────────────────▼───────────────────────────────────────────────┐
  │ ③ KNOWLEDGE GRAPH                                             (code) │
  │   Molecules · Reactions (hypothesis | observed) · Clues · Sources.   │
  │   Each clue is scored against the hypothesis it might support by     │
  │   one function — product similarity, reactant similarity, how        │
  │   similar the *transformation* is, same reaction class — giving the   │
  │   step a grade: direct / analog / weak / none.                       │
  └───────────────────────┬───────────────────────────────────────────────┘
  ┌───────────────────────▼───────────────────────────────────────────────┐
  │ ④ DEBATE                                                      (LLM)  │
  │   Builder and Skeptic share the same graph tools and argue in turns. │
  │   Every claim must cite node ids; code checks each citation, and an  │
  │   uncited or unsupported claim is discarded.                         │
  └───────────────────────┬───────────────────────────────────────────────┘
  ┌───────────────────────▼───────────────────────────────────────────────┐
  │ ⑤ VERDICT                                                     (code) │
  │   Unlikely   a blocked step, or a fatal objection backed by a        │
  │              published *failure*                                     │
  │   Uncertain  a step with no precedent, or a gap in the route          │
  │   Feasible   every step has direct/analog precedent, nothing stands   │
  │   Plausible  otherwise — and the cap for any un-debated route         │
  └───────────────────────────────────────────────────────────────────────┘
```

### Four decisions worth explaining

**Clues, not routes.** Asking a model "how do I make X" gets you a plausible-sounding answer for a
molecule nobody has made. Asking the literature "what reacted with what, how" gets you evidence,
which can be scored. Orchanium only ever collects clues; it assembles the route itself.

**Vendor pages are not evidence.** A supplier listing a compound tells you someone made it, not how
— and treating it as proof turns an evaluation into a lookup. Vendor sources are excluded from
evidence entirely. They are used for one narrow purpose: judging whether a *leaf* is actually
buyable — and only when it is much simpler than the target, so an advanced intermediate sold by a
catalogue cannot be passed off as a starting material.

**The critic is one table, not a hundred cases.** Chemistry incompatibilities come from a single
nucleophile × electrophile table, applied both inside a molecule (a precursor that would react with
itself) and across the inputs of a step (which reacting group wins). Adding a functional group adds
a row, not a branch.

**Failures are the most valuable clue.** In the ibuprofen run the Builder argued *against*
pressurised H₂/Pd-C, because a published failure precedent shows it over-reduces past the product.
That argument exists only because failed reactions are indexed alongside successful ones.

---

## Results

### Blind held-out tests

The hard part of evaluating this is that the answer for any known molecule is on the internet. So
there are two stricter modes:

- **Blind** — every source that names or contains the target is discarded before it reaches the graph.
- **Strict** — additionally, any precedent whose product is more than 45% similar to the target is
  dropped, so the system cannot lean on near-identical chemistry. It must generalise.

Targets were chosen by searching the USPTO corpus for reactions that are *not* widely written up, so
the route could not simply be found.

| Target | Mode | Steps recovered | Verdict | Confidence | Cost |
|---|---|---|---|---|---|
| US20160024004A1 (sulfonamide benzamide) | blind | **2 / 2** | Plausible | 0.67 | $0.30 |
| US20160024004A1 | **strict** | **2 / 2** | Plausible | 0.51 | $0.28 |
| US07732444B2 (pyrimidinyl benzylamine) | **strict** | 1 / 2 | Uncertain | 0.40 | $0.63 |
| Paracetamol | blind | full route | Feasible | 0.78 | $0.70 |

Both steps of US20160024004A1 came back under the strict cap, correctly classed, sharing reactants
with the real patent — with the confidence honestly dropping from 0.67 to 0.51 as the evidence was
taken away. On US07732444B2 it found the reductive amination but not the Suzuki coupling, and said
so: its own Skeptic flagged the weak step and the verdict came out *Uncertain*, not a confident
wrong answer.

### Live runs

| Target | Result | Cost |
|---|---|---|
| **Ibuprofen** | Recovered the real **3-step BHC industrial route** — Friedel–Crafts acylation → carbonyl reduction → Pd/CO carbonylation — with conditions from the patents (82 °C, isopropanol, MgO on activated carbon, 8 h). Feasible, 0.97, 27 sources | $0.48 |
| **A molecule with no PubChem record** | Feasible, 0.72, route back to buyable materials | $0.55 |

A full run costs roughly **$0.30–$0.70** and is capped — spend, token, search and tool-call budgets
are reserved per phase, so a long research phase cannot starve the debate.

### What it does not do yet

Stated plainly, because the limits matter as much as the results:

- **Source quality is not weighted in ranking.** A patent and a blog post currently carry the same
  weight once a clue is extracted; only structural similarity moves the score.
- **Most web citations cannot be verified.** Publishers block automated fetches, so the citation
  checker often has to report "unverifiable" rather than "verified". Patent citations check cleanly.
- **~20 reaction templates.** Enough for a large slice of medicinal chemistry, not for all of it.
- **Reasoning is connectivity-level**, not mechanistic. It argues about which bonds can be formed
  from what, with what precedent — not about transition states.
- **Meta's content filter occasionally blocks the debate prompt.** The run survives it: the report
  falls back to a deterministic template and the verdict is capped at Plausible with the reason
  stated.

---

## Running it

### Docker (one command)

```bash
cp .env.example .env    # then put your META_API_KEY in it
```

```bash
docker compose up --build
```

The UI is then at **http://localhost:5173**, the API at **http://localhost:8000**.

### Local

Backend (Python 3.12):

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r backend/requirements.txt
```

```bash
cd backend && uvicorn orchanium.api:app --port 8000 --reload
```

Frontend:

```bash
cd frontend && npm install && npm run dev
```

Or run one target straight from the command line, no UI:

```bash
cd backend && python -m orchanium.cli run "ibuprofen"
```

```bash
cd backend && python -m orchanium.cli run "ibuprofen" --blind --rounds 2
```

### Configuration

`.env` (never committed — the key belongs here, not in `.env.example`):

| Variable | Meaning |
|---|---|
| `META_API_KEY` | Meta Model API key. **Required.** `MODEL_API_KEY` also works |
| `META_MODEL` | Reasoning model, default `muse-spark-1.3` |
| `META_MODEL_CHEAP` | Model for high-volume, low-stakes calls |
| `SAM_MODEL` | Segmentation model for reading figures, default `sam-3.1` |
| `FETCH_CONTACT_URL` | A URL identifying you, sent in the citation checker's User-Agent. Wikipedia and some publishers refuse anonymous bots; set it to your repo URL |

Per-run guardrails (spend cap, call caps, route depth) live in
[`backend/orchanium/config.py`](backend/orchanium/config.py).

### The USPTO index (optional but recommended)

Without it, Orchanium still runs on web research and PubChem alone; with it, every step is also
checked against 1.45M real patent reactions.

```bash
python scripts/download_uspto.py
```

```bash
python scripts/build_uspto_index.py
```

This downloads Daniel Lowe's USPTO reaction dataset (CC0, via Figshare) and builds a fingerprint
index — about 2.4 GB of raw data, 600 MB of index, roughly 20 minutes. It lands in `data/uspto/`,
which `docker-compose.yml` mounts, so the container picks it up automatically.

### Tests

```bash
cd backend && python -m pytest
```

35 tests covering the critic's incompatibility logic, name/structure normalisation, precedent
scoring, the strict-JSON schema builder, and the route validator. The frontend is checked with
`npx tsc --noEmit`.

---

## Layout

```
backend/orchanium/
  orchestrator.py     the run: decompose → gather → debate → verdict, all emitted as events
  clues.py            the single ingest path, plus the evidence policy and blind/strict filters
  graph.py            the knowledge graph
  api.py              FastAPI + resumable server-sent events (sequence ids, resume, heartbeat)
  chem/               RDKit: reaction templates, similarity, the critic, purchasability, depiction
  agents/             planner · decomposer · graph tools · debate · verdict · citation check · reporter
  meta/client.py      Meta Model API: strict JSON schemas, tool loop, budget accounting
  sources/            USPTO index · web research
backend/prompts/      every agent prompt, as Markdown, editable without touching code
frontend/src/
  state/runStore.ts   the whole UI is a reduction over the event stream
  components/         result · graph · verification chain · debate · activity dock
scripts/              USPTO download and index build, held-out evaluation, smoke tests
PLAN.md               the build plan, with the verified Meta API shapes
```
