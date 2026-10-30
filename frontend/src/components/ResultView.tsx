import { routeSteps, sourceCount, targetName, useRun } from "../state/runStore";
import { firstClause, readable } from "../textutil";
import { GRADE, TONE, VERDICT, type Grade, type VerdictLabel } from "../tokens";
import { Card, GradeBadge, Label, Mono, Pill } from "./primitives";

function headline(label: string, steps: number, buyable: boolean) {
  if (!steps) return "No route could be assembled yet.";
  const from = buyable ? " from buyable starting materials" : "";
  switch (label) {
    case "Feasible":
      return `Can be made in ${steps} step${steps === 1 ? "" : "s"}${from}.`;
    case "Plausible":
      return `Probably makeable in ${steps} step${steps === 1 ? "" : "s"}${from}.`;
    case "Uncertain":
      return `A ${steps}-step route exists, but part of it is unproven.`;
    default:
      return `The evidence argues against this ${steps}-step route.`;
  }
}

function conditionsOf(s: ReturnType<typeof useRun.getState>, stepId: string): string {
  const step = s.report?.data.steps.find((x) => x.hypothesis_id === stepId);
  const best = step?.precedents?.find((p) => p.outcome === "success");
  if (best) {
    const c = best.conditions ?? {};
    const parts = [
      c.temperature_c != null ? `${c.temperature_c} °C` : null,
      c.solvent, c.catalyst, c.time,
    ].filter(Boolean);
    if (parts.length) return parts.join(", ");
    if (c.text) return String(c.text);
  }
  const reagents = s.reactions[stepId]?.classes?.[0];
  return reagents ? "see precedents" : "—";
}

export function ResultView() {
  const s = useRun();
  const steps = routeSteps(s);
  const v = s.verdict;
  const data = s.report?.data;
  const label = (v?.label ?? "Uncertain") as VerdictLabel;
  const meta = VERDICT[label] ?? VERDICT.Uncertain;
  const tone = meta.tone as keyof typeof TONE;

  const buyable = (data?.starting_materials?.length ?? 0) > 0;
  const totalSources = new Set(
    Object.values(s.prov).filter((n) => n.node_type === "source").map((n) => n.details?.url ?? n.id),
  ).size;

  if (!steps.length && s.status === "running") {
    return (
      <div className="mx-auto max-w-[940px] px-6 py-12">
        <Label>Working on {targetName(s)}</Label>
        <h1 className="mt-3 max-w-xl text-[30px] font-semibold leading-[1.18] tracking-[-0.02em]">
          Gathering published evidence for each candidate step…
        </h1>
        <p className="mt-3 max-w-lg text-muted">
          Orchanium cuts the target into candidate steps, then looks for real reactions that
          back each one up. The verdict appears when every step has been weighed.
        </p>
      </div>
    );
  }

  if (!steps.length && s.status === "idle") {
    return (
      <div className="mx-auto max-w-[940px] px-6 py-16">
        <Label>Literature-grounded retrosynthesis</Label>
        <h1 className="mt-3 max-w-2xl text-[36px] font-semibold leading-[1.12] tracking-[-0.024em]">
          Can this molecule be made, and how?
        </h1>
        <p className="mt-4 max-w-xl text-[14.5px] leading-relaxed text-muted">
          Name a molecule — even one that has never been made. Orchanium cuts it into candidate steps
          with RDKit, finds published reactions that back each step up, checks the chemistry in code,
          and has two agents argue over the evidence before it answers.
        </p>
        <div className="mt-8 grid max-w-3xl gap-4 sm:grid-cols-3">
          {[
            ["The model never invents structures", "Names are resolved through PubChem; cuts come from RDKit templates."],
            ["Verdicts are computed, not voted", "Agents argue, but a fixed rule over the evidence decides the label."],
            ["Every claim traces to a source", "Each step links back to the patents and papers behind it."],
          ].map(([t, d]) => (
            <Card key={t} className="p-4">
              <div className="text-[13.5px] font-medium">{t}</div>
              <div className="mt-1.5 text-[12.5px] leading-relaxed text-muted">{d}</div>
            </Card>
          ))}
        </div>
        <div className="mt-8 text-[12.5px] text-muted">
          Try <span className="text-ink">ibuprofen</span>, or paste a SMILES for a new compound.
        </div>
      </div>
    );
  }

  if (!steps.length) {
    return (
      <div className="mx-auto max-w-[940px] px-6 py-12">
        <Label>Result for {targetName(s)}</Label>
        <h1 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-0.02em]">
          No route was found.
        </h1>
        <p className="mt-3 max-w-lg text-muted">
          Nothing in the evidence connects this target back to buyable materials. Try a different
          target, or allow more research.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1040px] animate-rise px-6 py-10">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0 max-w-[620px]">
          <Label>Result for {targetName(s)}</Label>
          <h1 className="mt-3 text-[34px] font-semibold leading-[1.14] tracking-[-0.022em]">
            {headline(label, steps.length, buyable)}
          </h1>
          <p className="mt-4 text-[14px] leading-relaxed text-muted">
            {v?.reasons?.[0] ?? meta.note}
            {s.blind && (
              <>
                {" "}
                <span className="text-ink">
                  Blind mode was on: every source mentioning the target was discarded.
                </span>
              </>
            )}
          </p>
        </div>

        <div className="flex shrink-0 flex-col items-start gap-3">
          <Pill tone={tone}>{label}</Pill>
          <div className="text-[12.5px] text-muted">
            Confidence {v ? v.confidence.toFixed(2) : "—"} · {totalSources} sources cited
          </div>
          <div className="flex gap-2">
            <button
              className="btn-primary"
              onClick={() => {
                const md = s.report?.markdown ?? "";
                const blob = new Blob([md], { type: "text/markdown" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `orchanium-${s.targetInfo?.name ?? "route"}.md`;
                a.click();
              }}
              disabled={!s.report}
            >
              Export report
            </button>
            <button
              className="btn-secondary"
              onClick={() =>
                navigator.clipboard.writeText(
                  steps.map((x, i) => `${i + 1}. ${x.reaction}  [${x.classes[0] ?? ""}]`).join("\n"),
                )
              }
            >
              Copy route
            </button>
          </div>
        </div>
      </div>

      {/* step table */}
      <Card className="mt-9 overflow-hidden">
        <div className="grid grid-cols-[52px_1fr_190px_210px] gap-4 border-b border-hairline px-5 py-3">
          <Label>Step</Label>
          <Label>Reaction</Label>
          <Label>Conditions</Label>
          <Label>Evidence</Label>
        </div>
        {steps.map((step) => {
          const g = GRADE[step.grade as Grade] ?? GRADE.none;
          return (
            <div
              key={step.id}
              className="grid grid-cols-[52px_1fr_190px_210px] items-center gap-4 border-b border-hairline
                         px-5 py-4 last:border-0 transition-colors hover:bg-ground/60"
            >
              <div className="text-[22px] font-semibold tabular-nums">{step.index}</div>
              <div className="min-w-0">
                <div className="text-[14px] font-medium">{step.classes[0] ?? "Step"}</div>
                <div className="mt-0.5 truncate text-[13px] text-muted" title={step.reaction}>
                  {step.reaction}
                </div>
              </div>
              <Mono>{conditionsOf(s, step.id)}</Mono>
              <div className="flex items-center justify-between gap-3">
                <GradeBadge grade={step.grade} sources={sourceCount(s, step.id)} />
                <button
                  className="shrink-0 text-[12.5px] underline decoration-hairline underline-offset-4
                             transition-colors hover:decoration-ink"
                  onClick={() => {
                    s.select({ step: step.id });
                    s.setTab("verification");
                  }}
                >
                  See proof
                </button>
              </div>
              {step.objections.length > 0 && (
                <button
                  onClick={() => { s.select({ step: step.id }); s.setTab("debate"); }}
                  className="col-span-4 -mt-1 pl-[52px] text-left text-[12.5px] hover:underline"
                  style={{ color: TONE.warn.fg }}
                >
                  {step.objections.length} objection{step.objections.length === 1 ? "" : "s"} from the Skeptic
                  {" — "}{firstClause(step.objections[0].claim)}
                </button>
              )}
              {g.tone === "warn" && !step.objections.length && (
                <div className="col-span-4 -mt-1 pl-[52px] text-[12.5px] text-muted">{g.blurb}</div>
              )}
            </div>
          );
        })}
      </Card>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <Card className="p-5">
          <Label className="mb-3">Starting materials to buy</Label>
          {(data?.starting_materials ?? []).length ? (
            data!.starting_materials.map((name) => {
              const mol = Object.values(s.molecules).find((m) => m.name === name);
              return (
                <div
                  key={name}
                  className="flex items-center justify-between gap-4 border-b border-hairline py-2.5 last:border-0"
                >
                  <span className="truncate text-[13.5px]">{name}</span>
                  <Mono className="shrink-0 truncate text-right">{mol?.smiles ?? ""}</Mono>
                </div>
              );
            })
          ) : (
            <div className="text-[13px] text-muted">Not determined yet.</div>
          )}
        </Card>

        <Card className="p-5">
          <Label className="mb-3">Risks · test first</Label>
          <ul className="space-y-2.5 text-[13.5px] leading-relaxed">
            {(data?.debate?.sustained_objections ?? []).map((o) => (
              <li key={o.id} className="flex gap-2.5">
                <span className="mt-[7px] h-[5px] w-[5px] shrink-0 rounded-full" style={{ background: TONE.warn.fg }} />
                <span>{readable(o.claim, 230)}</span>
              </li>
            ))}
            {steps
              .filter((x) => x.grade === "weak" || x.grade === "none")
              .map((x) => (
                <li key={x.id} className="flex gap-2.5">
                  <span className="mt-[7px] h-[5px] w-[5px] shrink-0 rounded-full" style={{ background: TONE.warn.fg }} />
                  <span>
                    Step {x.index} has {x.grade === "none" ? "no published precedent" : "only thin precedent"}. Run it
                    at small scale first.
                  </span>
                </li>
              ))}
            {!data?.debate?.sustained_objections?.length &&
              !steps.some((x) => x.grade === "weak" || x.grade === "none") && (
                <li className="text-muted">No standing objections. Every step is backed by published work.</li>
              )}
          </ul>
          {v?.gaps?.length ? (
            <div className="mt-4 border-t border-hairline pt-3 text-[12.5px] text-muted">
              Unsolved: {v.gaps.map((g) => s.molecules[g]?.name ?? g).join(", ")}
            </div>
          ) : null}
        </Card>
      </div>

      {data?.evidence && (
        <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px] text-muted">
          <span>
            Evidence:{" "}
            {Object.entries(data.evidence.clues_by_source)
              .map(([k, n]) => `${n} ${k === "uspto" ? "patent records" : k}`)
              .join(" · ")}
          </span>
          <span>
            Citation checks:{" "}
            {Object.entries(data.evidence.citation_checks)
              .map(([k, n]) => `${n} ${k}`)
              .join(" · ")}
          </span>
          <Mono>${s.cost.usd.toFixed(3)} · {s.cost.searches} searches</Mono>
        </div>
      )}
    </div>
  );
}
