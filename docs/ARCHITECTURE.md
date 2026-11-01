# Orchanium — what it is and how it works

## The problem

A chemist with an idea for a molecule that has never been made has no way to ask
"can this be made, and how?" and get an answer they can check. They can search
the literature, but the literature does not contain their molecule. What it
contains is **clues**: thousands of reports of *this* material reacting with
*that* material, under these conditions, with this yield — scattered across
patents and papers that were never written about their target.

Retrosynthesis tools predict routes from learned patterns, but they answer with
a route, not with evidence, and you cannot ask one *why*.

## The idea

Orchanium collects those clues, connects them into one knowledge graph, and has
agents reason over that graph to judge whether a proposed molecule can be made —
and then shows its work, every claim traced back to the paper it came from.

Three commitments follow from that, and they shape the whole system:

1. **The answer is computed, not generated.** Agents argue; a fixed rule decides.
2. **Every claim has a source**, or it is marked as having none.
3. **What it learns, it keeps.** Evidence outlives the run that found it, and a
   result from your own bench outranks anything published.

---

## A run, end to end

The pipeline is a LangGraph state machine (`pipeline.py`). Nodes are plain async
functions; LangGraph owns the control flow and nothing else.

```
          ┌─────────┐   ┌───────────┐   ┌──────────┐
  target →│  plan   │──→│ decompose │──→│ evidence │──┐
          └─────────┘   └───────────┘   └──────────┘  │
                                                      │ debate rounds > 0 ?
                        ┌──────────┐   ┌───────────┐  │
            answer ←────│  report  │←──│  verdict  │←─┴──┐
                        └──────────┘   └───────────┘     │
                                             ▲    ┌──────┴──────┐
                                             └────│   debate    │
                                                  │ builder ⇄   │
                                                  │   skeptic   │
                                                  └─────────────┘
```

**Every node is allowed to fail.** `ctx.agent` reports the failure and the run
continues with whatever earlier phases produced, so a dead debate costs the
argument, not the answer. Only an unresolved target ends a run, because nothing
downstream means anything without a structure.

### plan — what molecule is this, really?

`agents/planner.py`. Takes a name or a SMILES string and resolves it to a
verified structure through PubChem, falling back to OPSIN for systematic names.
**An agent never writes a structure**; structures come from databases only.
RDKit then describes it (formula, rings, functional groups), and PubChem's
vendor list says whether it is already sold — which tells the user immediately
whether their "new" compound is actually new.

### decompose — what are the possible steps?

`agents/decomposer.py` with `chem/reactions.py`. A registry of reaction
templates (amide, ester, sulfonamide, ether, N-alkylation, reductive amination,
Suzuki coupling, Friedel–Crafts, nitro reduction and others) is applied in
reverse to cut the target into candidate precursors, recursively.

This is **RDKit, not an AI**. Every candidate step is then checked by the
chemistry critic (`chem/critic.py`), which is also pure code:

| Check | What it catches |
|---|---|
| parse | the species are real, sanitizable molecules |
| product differs | the "reaction" actually changes something |
| element balance | atoms are conserved, allowing for known by-products |
| conserved core | the product's skeleton really comes from the precursors |
| functional-group conflicts | groups that would attack each other |
| reaction class | the step is reproduced by a forward template |

A step the critic blocks can never appear in a route, whatever any agent says.

### evidence — find the clues

`clues.py` drives three sources, all producing the same `Clue` shape:

- **`sources/uspto.py`** — a local index of reaction records extracted from
  patents. Free to query, so it runs for every candidate step.
- **`memory.py`** — the lasting knowledge graph: clues found by *earlier runs*
  and notes from your own lab, recalled by product similarity.
- **`sources/web.py`** — an LLM with web search, asked for published reactions
  of the same kind on similar substrates, **including failures**. This costs
  money, so it is spent only where evidence is weakest on the most promising
  routes (`web_research_targets`).

Every clue is ingested the same way: molecules resolved against PubChem, the
clue recorded, and a provenance chain emitted —
`source → extraction → resolution` — so the UI can show where any number came
from without re-deriving it.

**Supplier pages are never evidence.** A product listing proves someone sells a
molecule; it says nothing about how it was made.

Then `graph.link_precedents()` scores each clue against each candidate step by
structural similarity, and grades the step:

| Grade | Meaning |
|---|---|
| `direct` | this exact reaction is published |
| `analog` | the same reaction type on closely related molecules |
| `weak` | only loosely similar reactions support it |
| `none` | nothing found |
| `blocked` | the chemistry critic ruled it out |

### debate — two agents argue over the graph

`agents/debate.py`, itself a LangGraph cycle:

```
builder → skeptic → another round? → builder → … → stop
```

- **Builder** proposes a route and defends it, step by step, with a procedure
  for each step (protect / activate / react / deprotect / work up / purify) and
  conditions. It may call `request_research` to go and find more evidence, or
  `propose_step` to add a step the templates never generated — which is how
  chemistry outside the template registry still reaches a route.
- **Skeptic** attacks it, raising objections with a severity, and must withdraw
  objections the evidence answers.

Both work through the same read-only graph tools (`agents/graph_tools.py`):
`overview`, `get_node`, `precedents`, `find_clues`. **Every citation an agent
makes is validated against the graph by code**; ids that do not exist are struck
out and recorded as struck, so a confident-sounding claim with an invented
source is visibly unsupported rather than quietly believed.

### verdict — the part that is not an AI

`agents/verdict.py`. A fixed rule over the graph and the surviving objections:

- any step blocked, or a fatal objection backed by a *reported failure* → **Unlikely**
- a step with no precedent, an unbuyable precursor, or too many weak steps and
  standing objections at once → **Uncertain**
- every step `direct` or `analog`, no major objection standing → **Feasible**
- otherwise → **Plausible**

Confidence is arithmetic on precedent scores, with deductions for objections,
gaps and lab failures. A route that was never reviewed by the Skeptic is capped
at Plausible, and the reason is stated. **The debate informs the verdict; it can
never override a computed grade.**

### report — say it in a chemist's language

`agents/reporter.py` assembles the data, and `agents/conditions.py` builds the
conditions table for each step, where every field carries its basis:

| Basis | Meaning |
|---|---|
| `lab` | your own lab note on this exact step |
| `reported` | a published record of exactly this step |
| `analog` | a published record of a close analog |
| `suggested` | the Builder's recommendation |
| `missing` | nobody reported it |

All reported fields for a step come from **one anchor source**, named above the
table, so the conditions describe a procedure someone actually ran rather than a
collage of four different papers. If the write-up model fails, a deterministic
template report is produced instead — the run still ends with an answer.

---

## The knowledge graph

`graph.py`. Molecules, reactions and clues, where a reaction is either a
**hypothesis** (a step we are considering) or an **observed** reaction (a step
someone reported). Precedent links connect the two, carrying a score.

Routes are assembled by searching backwards from the target to molecules that
can be bought, costing each step by its evidence. `metrics()` summarises a
route; `gaps` names precursors that are neither purchasable nor made by an
earlier step — which is how an incomplete route is reported honestly instead of
being padded.

Whether something is **purchasable** is itself judged (`chem/purchasable.py`),
not assumed: a molecule that is most of the target by heavy-atom count is an
advanced intermediate, not a starting material, even if a supplier lists it.

### It lasts

`memory.py` keeps every clue in SQLite beyond the run that found it. A later run
on a related molecule recalls them by product similarity, and they re-enter
through the normal ingest path — so all the usual filtering still applies. The
UI shows how many clues are known and how many came from your lab.

### It learns from your bench

`lab.py`. Each finished run snapshots its final graph. When you record what
happened when you actually ran a step, that note becomes a clue with
`origin="lab"` on that exact reaction — so it grades as `direct` and **outranks
every published source for that step**. The verdict is recomputed by the same
fixed rule, and a `revision` event records what changed and why, so the answer
never changes silently. The note also joins the lasting graph, so later runs see
it.

A lab failure with no lab success caps the answer at Uncertain and costs
confidence. A lab success counts as proven.

---

## Blind mode — how we test the claim

**Blind mode is for validation, not for use.** A chemist who wants the best
answer should leave it off, because it deliberately discards good evidence. It
exists to test whether the system can work *without being handed the answer*.

It asks two questions of every clue, rather than keeping a list of special
cases:

1. **Does this evidence describe the target's own chemistry?** — it is the
   molecule, it is built on the molecule's ring skeleton (what a chemical series
   and a patent family share), or it is a fingerprint near-twin.
2. **Does the document it came from know the target?** — it names it, it was
   held out by the caller, or another record in it already gave the answer away.

Either one hides the clue, and one leak anywhere in a document hides **every**
record from it, because a document that knows the answer leaks its conditions,
solvents and quantities just as surely as a structure. Separately, every name
the target is known by is scrubbed from every model request at the client
boundary, so an agent cannot recall a published route from the name.

`scripts/eval_holdout.py` goes further for measurement: it hides the patent,
every intermediate on the real route, and then scores the proposed route against
the real one automatically.

---

## Where the AI is, and where it is not

This boundary is the product.

| Done by code (deterministic) | Done by a model |
|---|---|
| structure resolution (PubChem / OPSIN) | finding published reactions on the web |
| disconnections (RDKit templates) | arguing which route is best (Builder) |
| the chemistry critic's six checks | attacking it (Skeptic) |
| precedent scoring and grading | writing the report's prose |
| route assembly and gap detection | suggesting conditions where none are reported |
| **the verdict and its confidence** | |
| citation validation | |
| blind-mode filtering | |

Agents choose and argue. They do not decide, and they cannot invent a molecule,
a citation or a grade.

---

## Plumbing

- **`context.py`** — `RunContext`, shared by every phase: the event bus, the
  Meta client, the target, blind-mode state, and the provenance node store. Also
  `ctx.agent()`, the context manager that reports an agent's status and swallows
  its failures.
- **`meta/client.py`** — the one way to reach the model. Strict structured
  outputs, a tool loop that still answers when it runs out of research turns, a
  response cache keyed on the scrubbed request, blind-mode scrubbing, and the
  budget guard. Phases reserve a share of the budget for the phases after them,
  so a long research phase cannot starve the debate.
- **`events.py` / `store.py`** — every run is an append-only event log in
  SQLite. The UI is a projection of that log, which is why a finished run can be
  replayed exactly, and why a lab note can append a revision to a run that ended
  hours ago.
- **`api.py`** — FastAPI: start a run, stream its events, add a lab note, read
  the knowledge graph's stats.
- **`frontend/`** — React and Zustand. The store consumes the same event stream
  live or replayed; the views render the route, the provenance chains, the
  debate and the lab notes.

## Layout

```
backend/orchanium/
  pipeline.py        the run as a LangGraph state machine
  orchestrator.py    what a run owns; the work each phase does
  graph.py           the knowledge graph, routes, grading
  clues.py           one ingest path for every source, blind filtering
  memory.py          the lasting knowledge graph
  lab.py             snapshots, lab notes, revisions
  context.py         per-run context shared by all agents
  agents/            planner, decomposer, debate, verdict, reporter,
                     conditions, citation_checker, graph_tools
  chem/              RDKit, reaction templates, critic, PubChem, similarity
  sources/           USPTO index, web research
  meta/              the model client and SAM
prompts/             one markdown file per agent
scripts/             the held-out evaluation
frontend/src/        React UI
docs/                this file, and the blind-test evidence
```

## What it does not do

- **Source quality is not weighted.** A patent and a blog post count the same
  once a clue is extracted; only structural similarity moves the score.
- **Most web citations cannot be verified**, because publishers block automated
  fetching. Patent citations check cleanly; the rest are marked unverifiable
  rather than claimed as checked.
- **The template registry is finite.** The Builder can propose steps outside it,
  but the automatic disconnection is limited to the templates in the registry.
- **Reasoning is connectivity-level, not mechanistic.** It argues about which
  bonds can be made from what, with what precedent — not about transition
  states.
- **Route accuracy is not yet measured at scale.** The held-out evaluation
  exists and runs; it has not been run across enough patents to report a number.
