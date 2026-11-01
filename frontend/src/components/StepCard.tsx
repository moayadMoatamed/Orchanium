import { ArrowDown, ArrowRight, FlaskConical, TriangleAlert } from "lucide-react";
import { routeSteps, sourceCount, useRun } from "../state/runStore";
import { firstClause, readable } from "../textutil";
import { TONE, reactionPlain } from "../tokens";
import { Card, GradeBadge, Pill } from "./primitives";
import { Structure } from "./Structure";

type S = ReturnType<typeof useRun.getState>;
export type Step = ReturnType<typeof routeSteps>[number];

/* The route's own view of a step. Conditions and the procedure belong to the
   Method tab, recording a result to Lab notes, and the evidence to Reasoning,
   so none of that is repeated here. */

export function MoleculeChip({ s, id, tag }: { s: S; id: string; tag: string }) {
  const m = s.molecules[id];
  if (!m) return null;
  return (
    <button
      onClick={() => { s.select({ molecule: id, step: null }); s.setTab("route"); }}
      className="group flex w-[156px] flex-col items-center rounded-card border border-hairline bg-surface p-2
                 text-center transition-colors hover:border-ink/25"
      title="Show on the route map"
    >
      <Structure smiles={m.smiles} width={136} height={92} framed={false} />
      <span className="mt-1 line-clamp-2 text-[12.5px] font-medium leading-snug">{m.name}</span>
      <span className="text-[11.5px] text-muted">{tag}</span>
    </button>
  );
}

/** A step's title tells it apart from the others: the Builder's name when
 *  there is one, otherwise the reaction type and what it makes. */
export function stepTitle(s: S, step: Step) {
  if (step.name) return step.name;
  const product = step.product ? s.molecules[step.product]?.name : null;
  return `${step.classes[0] ?? "Chemical step"}${product ? ` → ${product}` : ""}`;
}

/** The route at a glance: one line per step. Conditions, the procedure and
 *  recording a result all live on their own tabs — this answers only "what
 *  are the steps, and how well is each one backed?" */
export function RouteStepRow({ s, step, target }: { s: S; step: Step; target: string | null }) {
  const d = step.detail;
  const lab = (d?.lab_successes ?? 0) > 0 ? "good" : (d?.lab_failures ?? 0) > 0 ? "bad" : null;
  return (
    <>
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold leading-snug">{stepTitle(s, step)}</div>
            <div className="mt-0.5 text-[13px] text-muted">
              {step.classes[0] ?? "Chemical step"} · {reactionPlain(step.classes[0]).toLowerCase()}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {lab && (
              <Pill tone={lab === "good" ? "lab" : "bad"}
                    title={lab === "good" ? "Your lab note says this step worked" : "Your lab note says this step failed"}>
                <FlaskConical size={13} aria-hidden /> {lab === "good" ? "Done in your lab" : "Failed in your lab"}
              </Pill>
            )}
            <GradeBadge grade={step.grade} sources={sourceCount(s, step.id)} />
          </div>
        </div>

        {step.objections.length > 0 && (
          <button
            onClick={() => { s.select({ step: step.id }); s.setTab("reasoning"); }}
            className="mt-3 flex w-full items-start gap-2 rounded-chip px-3 py-2 text-left text-[13px] leading-relaxed
                       transition-colors hover:brightness-95"
            style={{ background: TONE.warn.bg, color: TONE.warn.fg }}
          >
            <TriangleAlert size={15} strokeWidth={1.8} className="mt-[2px] shrink-0" aria-hidden />
            <span>
              Skeptic: {step.objections[0].plain
                ? readable(step.objections[0].plain, 200)
                : firstClause(step.objections[0].claim, 140)}
            </span>
          </button>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-4 text-[12.5px]">
          <button className="inline-flex items-center gap-1 text-muted hover:text-ink"
                  onClick={() => s.setTab("method")}>
            Conditions and procedure <ArrowRight size={13} strokeWidth={2} aria-hidden />
          </button>
          <button className="inline-flex items-center gap-1 text-muted hover:text-ink"
                  onClick={() => { s.select({ step: step.id, node: null }); s.setTab("reasoning"); }}>
            Why we trust this step <ArrowRight size={13} strokeWidth={2} aria-hidden />
          </button>
        </div>
      </Card>

      {step.product && (
        <div className="mt-3 flex items-center gap-3">
          <ArrowDown size={15} strokeWidth={1.8} className="text-muted" aria-hidden />
          <MoleculeChip s={s} id={step.product} tag={step.product === target ? "the target" : "made in this step"} />
        </div>
      )}
    </>
  );
}
