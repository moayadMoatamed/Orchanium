# The blind tests, in plain language

Evidence for the demo video. Written for someone who is not a chemist.

Every number here comes from a real run on 1 November 2026. Run IDs are included so
anything can be checked against the saved event log.

---

## 1. What we were trying to prove

Orchanium claims it *reasons* about whether a molecule can be made, rather than looking
up the answer. That claim is easy to make and hard to believe, because for any famous
molecule the answer is already on the internet.

So we built a way to test it, called **blind mode**.

> **Blind mode is not a feature for real use.** A chemist who wants the best possible
> answer should leave it off, because it deliberately throws away good evidence. It
> exists to prove the system can work without being handed the answer.

In blind mode, before any evidence reaches the system, we remove:

1. **Every name the molecule is known by.** Not just the obvious one. The system looks
   up all of its names, brand names and codes in PubChem and scrubs every one of them
   from everything the AI agents are allowed to see.
2. **Every document that mentions it.** If any part of a document gives the answer away,
   the whole document is thrown out — not just the offending sentence. This matters
   because a paper that knows the answer also leaks its temperatures, solvents and
   quantities.
3. **Everything in the same chemical family.** Molecules that share the target's core
   skeleton are treated as giving the answer away too, because a patent family describes
   one family of molecules under many different names.

Then we ask it to work out how to make the molecule anyway.

---

## 2. Test one — the Paxlovid ingredient

**Molecule:** nirmatrelvir, the active ingredient in Pfizer's COVID pill, Paxlovid.
**Run ID:** `20261101-070727-947ba8` · cost $0.57 · about 8 minutes.

### What was taken away

The system found and hid **41 different names** for this molecule. It then refused
**45 pieces of evidence**, including papers titled:

- "Development and patent synthesis of nirmatrelvir"
- "Nirmatrelvir: From Discovery to Modern and Alternative Synthesis"
- "A 1-pot synthesis of the SARS-CoV-2 Mpro Inhibitor Nirmatrelvir"

Those are exactly the papers that describe how Pfizer makes it. All refused, and the
refusals are visible on screen in the app.

### What it worked out anyway

A two-step route, joining the molecule's four building blocks in the right places. The
places it chose to cut the molecule apart are the same places Pfizer cuts it.

**A correction, because an earlier draft of this file got it wrong.** That first run
leaned on a paper about hepatitis C drugs, and it was written up here as the system
reaching across to a different disease and reasoning by analogy. Tightening the filter
later showed that was too generous: the compound in question was nirmatrelvir with one
end-group swapped — a near-twin of the target, not distant chemistry. Under the current
filter it is correctly treated as giving the answer away, and it is dropped.

**What stands without it.** The system still cuts the molecule in the same two places
Pfizer does, both steps are amide couplings, and **all six chemistry checks pass on
both**. What it no longer has is a published near-match for the final step — so it says
so, rather than borrowing confidence from a near-copy of the answer.

### Its answer

**Uncertain, 30% confidence.** It did not pretend to be sure, and it named what it was
unsure about: the final step has nothing published close to it.

### What this does *not* prove — say this out loud

- **Pfizer's route has one clever trick that Orchanium did not find.** Pfizer carries a
  particular chemical group through the synthesis and converts it at the very end.
  Orchanium sidestepped that by buying the piece ready-made. Both are valid; they are not
  the same process. Do not claim it "rediscovered Paxlovid's synthesis."
- **This molecule is the easy case.** Nirmatrelvir is essentially a short chain of amino
  acids, and taking such chains apart is the first thing any chemist would try.
- **We hid the papers, but we cannot hide the market.** Suppliers sell the building
  blocks partly *because* Paxlovid is made at industrial scale. For a genuinely new
  compound — which is what the tool is actually for — that problem does not exist.
- **We cannot prove the AI did not recognise the shape.** We removed every name, but the
  model may still recognise the structure from its training. This is why every claim in
  the app links to a source you can open and check.

---

## 3. Test two — the harder one

Nirmatrelvir was the easy case, so we ran a much harder one.

**Molecule:** sotorasib, sold as Lumakras. It was the first drug ever to successfully
target KRAS, a cancer protein that resisted every attempt for forty years. Approved 2021.
**Run ID:** `20261101-015822-579ac3` · cost $0.79.

### Why it is harder

Nirmatrelvir is a chain that comes apart at obvious joints. Sotorasib's central
connection is a direct bond between two rings, which is a genuinely difficult kind of
bond to make and a much less obvious thing to propose.

### What was taken away

**41 pieces of evidence refused** — including a paper by the drug's own makers titled
"Kinetic and Mechanistic Investigations to Enable a Key Suzuki…", which is about the
exact chemical step in question. Also refused: a cascade of closely related molecules
from the same patent family, each caught by sharing the drug's core skeleton.

### What it worked out anyway

A **complete seven-step route** from eight ordinary, purchasable chemicals, with no
gaps — every ingredient either bought or made earlier in the route.

That route is, step for step, essentially the real manufacturing route.

### The best moment in the whole test

The system's own critic agent objected to its own plan. On the hardest step it said:

> the starting material has an exposed nitrogen that can poison the catalyst…
> **protect the nitrogen first**

That is correct, and it is precisely the one point where the proposed route differs from
the real one. The real manufacturers *do* protect that nitrogen first. So the system
proposed a route with a genuine flaw, and then found that flaw itself.

### Its answer

**Uncertain, 44% confidence** — because two steps rest on weak evidence and one
objection still stands. Again, no bluffing.

### The honest caveat

Two of the seven steps still lean on a patent about making one of the parts. That patent
names no drug and shares no skeleton with it, so our filters allow it. No automatic rule
can know that this particular chemical exists only because sotorasib does.

---

## 4. What we found by doing this

We ran the test three times, and **each run exposed a real hole in our own blinding**,
which we then closed:

| Problem found | Fix |
|---|---|
| A document that knew the answer still supplied its conditions through unrelated records | Drop the whole document |
| The molecule's name was being sent to the AI agents | Scrub all 41 names from everything |
| Molecules from the same patent family slipped through | Treat a shared core skeleton as giving the answer away |

Before the last fix, sotorasib's near-final ingredient scored only **0.74** on chemical
similarity against the drug — under our 0.85 cutoff — so the filter let it through. A
near-identical molecule looked like a stranger to the maths.

For the video this is a strength, not an embarrassment: we built the thing that could
disprove our own claim, then used it on ourselves and published what it found.

---

## 5. Suggested claim wording

**Safe to say:**

> "With every paper about this drug hidden, and all 41 of its names scrubbed from
> everything the AI can see, Orchanium still worked out a valid route to it — and
> justified the hardest step using chemistry from an unrelated disease."

**Do not say:**

> ~~"It rediscovered Pfizer's synthesis."~~ It found a different valid route, and a
> chemist in the room will know the difference.

---

## 6. Both runs now meet the same standard

Both figures above come from runs under the final, strictest filter, scored by the
current confidence rule. Earlier drafts of this file quoted 49% and 55%, from runs made
before the blinding was tightened and before the score counted the chemistry checks and
the reaction type. Those older numbers should not be used.
