import {
  ArrowDown, ArrowRight, Droplets, Filter, FlaskConical, Lock, LockOpen, NotebookPen, ShieldAlert,
  TriangleAlert, Zap, type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { routeSteps, sourceCount, useRun } from "../state/runStore";
import type { ConditionField, LabNoteRecord, Operation } from "../state/types";
import { firstClause, readable } from "../textutil";
import { BASIS, GRADE, OPERATION, TONE, reactionPlain, type Grade } from "../tokens";
import { LabNoteDialog } from "./LabNoteDialog";
import { Card, GradeBadge, MoreText, Pill } from "./primitives";
import { Structure } from "./Structure";

type S = ReturnType<typeof useRun.getState>;
export type Step = ReturnType<typeof routeSteps>[number];

const OP_ICON: Record<string, LucideIcon> = {
  protect: Lock, activate: Zap, react: FlaskConical, deprotect: LockOpen, workup: Droplets, purify: Filter,
};
const FIELD_LABEL: Record<string, string> = {
  reagents: "Reagents", solvent: "Solvent", temperature: "Temperature", time: "Time",
  atmosphere: "Atmosphere", yield: "Yield",
};

export function MoleculeChip({ s, id, tag }: { s: S; id: string; tag: string }) {
  const m = s.molecules[id];
  if (!m) return null;
  return (
    <button
      onClick={() => { s.select({ molecule: id, step: null }); s.setTab("graph"); }}
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

function Procedure({ ops }: { ops: Operation[] }) {
  const quoted = new Set<string>();       // quote each objection once, at the first operation it shaped
  return (
    <ol className="mt-4 space-y-2.5">
      {ops.map((op, i) => {
        const firstMention = !!op.responds_to && !quoted.has(op.responds_to);
        if (op.responds_to) quoted.add(op.responds_to);
        const Icon = OP_ICON[op.kind] ?? FlaskConical;
        const meta = OPERATION[op.kind];
        const main = op.kind === "react";
        return (
          <li key={i} className="flex gap-3 text-[13.5px] leading-relaxed">
            <span
              className={`mt-[1px] grid h-6 w-6 shrink-0 place-items-center rounded-full border
                ${main ? "border-ink/40 bg-ink text-surface" : "border-hairline bg-surface text-muted"}`}
              title={meta?.plain}
            >
              <Icon size={13} strokeWidth={1.9} aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <div>
                <span className="mr-1.5 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-muted">
                  {meta?.label ?? op.kind}
                </span>
                {op.action}
              </div>
              {(op.reagents.length > 0 || op.why) && (
                <div className="text-[12.5px] text-muted">
                  {op.reagents.length > 0 && <span className="text-ink/80">{op.reagents.join(", ")}</span>}
                  {op.reagents.length > 0 && op.why && " · "}
                  {op.why}
                  {!op.backed && <span className="italic"> · no source cited</span>}
                </div>
              )}
              {op.responds_to && (
                <div className="mt-1 text-[12.5px]" style={{ color: TONE.warn.fg }}>
                  Added after the Skeptic objected
                  {firstMention && op.responds_to_text ? `: ${firstClause(op.responds_to_text, 120)}` : ""}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function BasisTag({ f }: { f: ConditionField }) {
  const b = BASIS[f.basis] ?? BASIS.missing;
  const t = TONE[b.tone];
  const title = `${b.hint}${f.source ? `: ${f.source}` : ""}${f.n && f.n > 1 ? ` (${f.n} reports)` : ""}`;
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-[1px] text-[11.5px]"
      style={{ color: t.fg, borderColor: t.border, background: t.bg }}
    >
      {f.basis === "lab" && <FlaskConical size={11} strokeWidth={2} aria-hidden />}
      {b.word}
    </span>
  );
}

/** `omit`: fields shown elsewhere (a procedure names its own reagents). */
function ConditionsTable({ fields, omit = [] }: { fields: Record<string, ConditionField>; omit?: string[] }) {
  const rows = Object.entries(fields).filter(([k]) => !omit.includes(k));
  const known = rows.filter(([, f]) => f.value);
  const missing = rows.filter(([, f]) => !f.value).map(([k]) => FIELD_LABEL[k] ?? k);
  const anchor = known.find(([, f]) => f.source)?.[1];
  return (
    <div className="mt-4">
      <div className="label mb-2">Conditions</div>
      {anchor && (
        <div className="-mt-1 mb-2 text-[12.5px] text-muted">
          Reported values from one source:{" "}
          {anchor.url
            ? <a href={anchor.url} target="_blank" rel="noreferrer" className="hover:text-ink hover:underline">{anchor.source}</a>
            : anchor.source}
        </div>
      )}
      {known.length ? (
        <dl className="grid grid-cols-[96px_1fr_auto] items-baseline gap-x-4 gap-y-1.5 text-[13px]">
          {known.map(([k, f]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{FIELD_LABEL[k] ?? k}</dt>
              <dd className="min-w-0">
                {f.value}
                {f.range && <span className="text-muted"> · {f.range} across {f.n} reports</span>}
              </dd>
              <dd><BasisTag f={f} /></dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="text-[13px] text-muted">No source reported conditions for this step.</div>
      )}
      {known.length > 0 && missing.length > 0 && (
        <div className="mt-1.5 text-[12.5px] text-muted">Not reported anywhere: {missing.join(", ").toLowerCase()}.</div>
      )}
    </div>
  );
}

/** Runs from before conditions records: the best precedent's own fields. */
function legacyConditions(s: S, stepId: string): string | null {
  const step = s.report?.data.steps.find((x) => x.hypothesis_id === stepId);
  const c = step?.precedents?.find((p) => p.outcome === "success")?.conditions ?? {};
  const parts = [c.temperature_c != null ? `${c.temperature_c} °C` : null, c.solvent, c.catalyst, c.time].filter(Boolean);
  return parts.length ? parts.join(" · ") : (c.text ?? null);
}

function LabNotes({ notes }: { notes: LabNoteRecord[] }) {
  const t = TONE.lab;
  return (
    <div className="mt-4 rounded-chip border px-3.5 py-2.5" style={{ borderColor: t.border, background: t.bg }}>
      <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.08em]" style={{ color: t.fg }}>
        <FlaskConical size={13} strokeWidth={2} aria-hidden /> From your lab
      </div>
      {notes.map((n) => {
        const bits = [
          n.yield_pct != null ? `${n.yield_pct}% yield` : null,
          n.conditions.temperature_c != null ? `${n.conditions.temperature_c} °C` : null,
          n.conditions.solvent, n.conditions.time, n.reagents.join(", ") || null,
          n.conditions.text,
        ].filter(Boolean);
        return (
          <div key={n.id} className="mt-1.5 text-[13px] leading-relaxed">
            <span className="font-medium" style={{ color: n.outcome === "success" ? TONE.good.fg : TONE.bad.fg }}>
              {n.outcome === "success" ? "Worked" : "Did not work"}
            </span>
            {bits.length > 0 && <span className="text-muted"> · {bits.join(" · ")}</span>}
            {n.observations && <div className="text-ink/85">“{n.observations}”</div>}
          </div>
        );
      })}
    </div>
  );
}

export function StepCard({ s, step, buy, target, finished }: {
  s: S; step: Step; buy: string[]; target: string | null; finished: boolean;
}) {
  const [noting, setNoting] = useState(false);
  const d = step.detail;
  const ops = d?.procedure ?? [];
  const objections = step.objections;
  const labNotes = d?.lab_notes ?? [];
  const unguarded = d?.competing_groups && !ops.some((o) => o.kind === "protect");
  const newInputs = step.reactants.filter((r) => buy.includes(r) && step.index > 1);
  const legacy = d?.conditions ? null : legacyConditions(s, step.id);
  const g = GRADE[step.grade as Grade] ?? GRADE.none;

  return (
    <>
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[15.5px] font-semibold leading-snug">{stepTitle(s, step)}</div>
            <div className="mt-0.5 text-[13px] text-muted">
              {step.classes[0] ?? "Chemical step"} · {reactionPlain(step.classes[0]).toLowerCase()}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {(d?.lab_successes ?? 0) > 0 && (
              <Pill tone="lab" title="Your lab note says this step worked"><FlaskConical size={13} aria-hidden /> Done in your lab</Pill>
            )}
            {(d?.lab_failures ?? 0) > 0 && !(d?.lab_successes ?? 0) && (
              <Pill tone="bad" title="Your lab note says this step failed"><FlaskConical size={13} aria-hidden /> Failed in your lab</Pill>
            )}
            <GradeBadge grade={step.grade} sources={sourceCount(s, step.id)} />
          </div>
        </div>

        {d?.plain && <p className="mt-3 text-[13.5px] leading-relaxed">{readable(d.plain, 400)}</p>}
        {!d?.plain && <p className="mt-3 text-[13.5px] leading-relaxed text-muted">{g.plain}</p>}

        {newInputs.length > 0 && (
          <div className="mt-3 text-[13px]">
            <span className="text-muted">Brings in </span>
            {newInputs.map((r) => s.molecules[r]?.name ?? r).join(", ")}
          </div>
        )}

        {ops.length > 0 && <Procedure ops={ops} />}

        {d?.conditions ? (
          <ConditionsTable fields={d.conditions} omit={ops.length ? ["reagents"] : []} />
        ) : (
          <div className="mt-4 text-[13px]">
            <span className="text-muted">Conditions: </span>
            {legacy ?? <span className="text-muted">not reported in the sources</span>}
          </div>
        )}

        {unguarded && (
          <div className="mt-4 flex gap-2 rounded-chip px-3 py-2 text-[13px] leading-relaxed"
               style={{ background: TONE.warn.bg, color: TONE.warn.fg }}>
            <ShieldAlert size={15} strokeWidth={1.8} className="mt-[2px] shrink-0" aria-hidden />
            <span>
              The chemistry check found groups that could react in the wrong place, and the procedure does not
              protect them. <MoreText short="" full={readable(d!.competing_groups!, 400)} />
            </span>
          </div>
        )}

        {objections.map((o) => (
          <button
            key={o.id}
            onClick={() => { s.select({ step: step.id }); s.setTab("debate"); }}
            className="mt-3 flex w-full items-start gap-2 rounded-chip px-3 py-2 text-left text-[13px] leading-relaxed
                       transition-colors hover:brightness-95"
            style={{ background: TONE.warn.bg, color: TONE.warn.fg }}
          >
            <TriangleAlert size={15} strokeWidth={1.8} className="mt-[2px] shrink-0" aria-hidden />
            <span>Skeptic: {o.plain ? readable(o.plain, 260) : firstClause(o.claim, 150)}</span>
          </button>
        ))}

        {labNotes.length > 0 && <LabNotes notes={labNotes} />}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          {finished ? (
            <button
              className="inline-flex items-center gap-1.5 rounded-chip border px-2.5 py-1 text-[12.5px] font-medium
                         transition-colors hover:brightness-95"
              style={{ color: TONE.lab.fg, borderColor: TONE.lab.border, background: TONE.lab.bg }}
              onClick={() => setNoting(true)}
              title="Record what happened when you ran this step"
            >
              <NotebookPen size={14} strokeWidth={1.8} aria-hidden /> I ran this
            </button>
          ) : <span />}
          <button
            className="inline-flex items-center gap-1 text-[12.5px] text-muted hover:text-ink"
            onClick={() => { s.select({ step: step.id, node: null }); s.setTab("verification"); }}
          >
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

      {noting && <LabNoteDialog step={step} title={stepTitle(s, step)} onClose={() => setNoting(false)} />}
    </>
  );
}
