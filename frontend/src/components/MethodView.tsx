import { Download, ShieldCheck, TriangleAlert } from "lucide-react";
import { routeSteps, stepCount, targetName, useRun } from "../state/runStore";
import type { ConditionField } from "../state/types";
import { BASIS, GRADE, OPERATION, TONE } from "../tokens";
import { Card } from "./primitives";
import { stepTitle, type Step } from "./StepCard";

const ORDER = ["reagents", "base", "coupling", "solvent", "ph", "temperature", "time", "equiv", "yield"];
const LABEL: Record<string, string> = {
  reagents: "Reagent", base: "Base", coupling: "Coupling", solvent: "Solvent", ph: "pH",
  temperature: "Temp", time: "Time", equiv: "Equiv", atmosphere: "Atmosphere", yield: "Yield",
};
/** Values a source actually reported read plainly; anything inferred is
 *  underlined, so a chemist can see at a glance what is evidence and what is
 *  our suggestion, without reading a legend for every row. */
const INFERRED = new Set(["analog", "suggested"]);

const WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
               "Ten", "Eleven", "Twelve"];
const spell = (n: number) => WORDS[n] ?? `${n}`;

/** The preparation method: every operation a chemist would actually run, in
 *  order, with the conditions and where each one came from. */
export function MethodView() {
  const s = useRun();
  const steps = routeSteps(s);
  const data = s.report?.data;
  const count = stepCount(steps);

  if (!steps.length || !data) {
    return (
      <div className="mx-auto max-w-[620px] px-6 py-24 text-center">
        <div className="text-[16px] font-semibold">No method yet</div>
        <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
          Run a molecule and the preparation method appears here, step by step.
        </p>
      </div>
    );
  }

  const weakest = [...steps].sort(
    (a, b) => (a.score ?? 0) - (b.score ?? 0) || (a.index - b.index))[0];

  return (
    <div className="mx-auto max-w-[940px] px-6 py-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="label">Preparation method</div>
          <h1 className="mt-2.5 max-w-2xl text-[30px] font-semibold leading-[1.15] tracking-[-0.02em]">
            {spell(count.total)} step{count.total === 1 ? "" : "s"}
            {count.protection > 0 && `, including ${spell(count.protection).toLowerCase()} to protect and unprotect`}.
          </h1>
        </div>
        <button className="btn-secondary shrink-0" onClick={() => exportMethod(s, steps)}>
          <Download size={14} strokeWidth={1.9} aria-hidden /> Export method
        </button>
      </div>

      {count.protection > 0 && (
        <p className="mt-3 max-w-2xl text-[13.5px] leading-relaxed text-muted">
          The {spell(count.reactions).toLowerCase()}-step summary on the Route tab counts only the steps that
          build the molecule. The published chemistry needs other groups blocked first, so this is the
          method as a chemist would run it.
        </p>
      )}

      <Legend />

      <div className="mt-6 space-y-4">
        {steps.map((step) => (
          <MethodStep key={step.id} s={s} step={step} testFirst={step.id === weakest.id && (step.score ?? 0) < 0.55} />
        ))}
      </div>

      {data.starting_materials?.length > 0 && (
        <Card className="mt-6 p-5">
          <div className="label mb-2">What to buy</div>
          <ul className="space-y-1 text-[13.5px]">
            {data.starting_materials.map((m) => (
              <li key={m} className="flex gap-2"><span className="text-muted">·</span>{m}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-1.5 rounded-card border border-hairline
                    bg-surface px-4 py-2.5 text-[12.5px] text-muted">
      <span className="font-medium text-ink">How to read the conditions</span>
      <span><span className="text-ink">Plain value</span> — reported in the cited source</span>
      <span>
        <span className="text-ink underline decoration-dotted decoration-from-font underline-offset-[3px]">
          Underlined
        </span>{" "}
        — inferred from a close reaction
      </span>
      <span><span className="text-ink">—</span> not reported anywhere</span>
    </div>
  );
}

function MethodStep({ s, step, testFirst }: { s: ReturnType<typeof useRun.getState>; step: Step; testFirst: boolean }) {
  const d = step.detail;
  const fields = (d?.conditions ?? {}) as Record<string, ConditionField>;
  const g = GRADE[step.grade as keyof typeof GRADE] ?? GRADE.none;
  const sources = d?.precedents?.length ?? 0;
  const ops = d?.procedure ?? [];
  const protection = ops.filter((o) => o.kind === "protect" || o.kind === "deprotect");
  const objection = step.objections?.[0];
  const anchor = Object.values(fields).find((f) => f.source);
  const tone = testFirst ? TONE.warn : null;

  return (
    <Card className="overflow-hidden p-0" tone={testFirst ? "warn" : undefined}>
      <div className="flex flex-wrap items-start gap-3 px-5 pt-4">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full
                         border border-hairline text-[12px] font-semibold text-muted">
          {step.index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold leading-snug">{stepTitle(s, step)}</span>
            {protection.length > 0 && (
              <span className="rounded-chip border border-hairline px-1.5 py-0.5 text-[10.5px]
                               font-semibold uppercase tracking-[0.07em] text-muted">
                Protection
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[12.5px] text-accent">{step.reaction}</div>
        </div>
        {testFirst ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-chip border px-2 py-0.5 text-[12px] font-medium"
                style={{ color: tone!.fg, borderColor: tone!.border, background: tone!.bg }}>
            <TriangleAlert size={12} strokeWidth={2} aria-hidden /> Test this first
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-chip border px-2 py-0.5 text-[12px]"
                style={{ color: TONE[g.tone as keyof typeof TONE].fg,
                         borderColor: TONE[g.tone as keyof typeof TONE].border,
                         background: TONE[g.tone as keyof typeof TONE].bg }}>
            <ShieldCheck size={12} strokeWidth={2} aria-hidden /> {g.label}
            {sources > 0 && <span className="opacity-75">· {sources} source{sources === 1 ? "" : "s"}</span>}
          </span>
        )}
      </div>

      <ConditionStrip fields={fields} />

      <div className="space-y-2 px-5 pb-4 text-[13px] leading-relaxed">
        {ops.length > 0 && (
          <div className="text-muted">
            Plan: {ops.map((o) => OPERATION[o.kind]?.label ?? o.kind).join(" → ")}
          </div>
        )}
        {d?.plain && <p>{d.plain}</p>}
        {testFirst && (
          <p style={{ color: TONE.warn.fg }}>
            Weakest step. {objection?.plain || objection?.claim ||
              "The published evidence for it is thin."} Run it at small scale before committing material.
          </p>
        )}
        {!testFirst && objection && (
          <p className="text-muted">{objection.plain || objection.claim}</p>
        )}
        {anchor && (
          <div className="pt-0.5 text-[12.5px] text-muted">
            Reported values from{" "}
            {anchor.url
              ? <a href={anchor.url} target="_blank" rel="noreferrer"
                   className="underline decoration-hairline underline-offset-2 hover:text-ink">{anchor.source}</a>
              : anchor.source}
          </div>
        )}
      </div>
    </Card>
  );
}

function ConditionStrip({ fields }: { fields: Record<string, ConditionField> }) {
  const shown = ORDER.filter((k) => k in fields);
  if (!shown.length) return <div className="mt-3 border-t border-hairline" />;
  return (
    <div className="mt-3.5 grid border-y border-hairline bg-ground/40"
         style={{ gridTemplateColumns: `repeat(${Math.min(shown.length, 6)}, minmax(0, 1fr))` }}>
      {shown.map((k) => {
        const f = fields[k];
        const basis = BASIS[f.basis] ?? BASIS.missing;
        const inferred = INFERRED.has(f.basis);
        return (
          <div key={k} className="min-w-0 border-r border-hairline px-3 py-2.5 last:border-r-0" title={basis.hint}>
            <div className="label text-[9.5px]">{LABEL[k] ?? k}</div>
            <div className={`mt-1 break-words text-[12.5px] ${inferred
              ? "underline decoration-dotted decoration-from-font underline-offset-[3px]" : ""}`}
                 style={f.basis === "lab" ? { color: TONE.lab.fg } : undefined}>
              {f.value ?? <span className="text-muted">—</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function exportMethod(s: ReturnType<typeof useRun.getState>, steps: Step[]) {
  const lines = [`# ${targetName(s)} — preparation method`, ""];
  for (const step of steps) {
    const f = (step.detail?.conditions ?? {}) as Record<string, ConditionField>;
    lines.push(`## Step ${step.index}. ${step.name ?? step.classes[0] ?? "Step"}`, "", step.reaction, "");
    for (const k of ORDER.filter((x) => x in f)) {
      const v = f[k];
      lines.push(`- **${LABEL[k] ?? k}:** ${v.value ?? "not reported"}` +
                 (v.value ? `  _(${(BASIS[v.basis] ?? BASIS.missing).word.toLowerCase()})_` : ""));
    }
    const src = Object.values(f).find((x) => x.source);
    if (src) lines.push("", `Reported values from ${src.source}${src.url ? ` — ${src.url}` : ""}`);
    lines.push("");
  }
  const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${targetName(s).replace(/[^\w.-]+/g, "-").toLowerCase()}-method.md`;
  a.click();
  URL.revokeObjectURL(a.href);
}
