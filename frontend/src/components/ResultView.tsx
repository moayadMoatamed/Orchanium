import type { ReactNode } from "react";
import {
  ArrowDown, ArrowRight, BookOpen, CircleAlert, Copy, Download, FileCheck2, FlaskConical, Library,
  Microscope, PackageCheck, RotateCcw, Scale, ShieldCheck, Target, TriangleAlert,
} from "lucide-react";
import { failureOf, routeStory, sourceCount, targetName, useRun } from "../state/runStore";
import { firstClause, firstSentence, plural, readable } from "../textutil";
import {
  GRADE, TONE, VERDICT, confidenceWords, reactionPlain, type Grade, type VerdictLabel,
} from "../tokens";
import { Card, GradeBadge, MoreText, Section } from "./primitives";
import { Structure } from "./Structure";

type S = ReturnType<typeof useRun.getState>;

function headline(label: string, steps: number, buyable: boolean) {
  if (!steps) return "No route could be assembled.";
  const n = plural(steps, "step");
  const from = buyable ? " from chemicals you can buy" : "";
  switch (label) {
    case "Feasible":
      return `Can be made in ${n}${from}.`;
    case "Plausible":
      return `Probably makeable in ${n}${from}.`;
    case "Uncertain":
      return `A ${steps}-step route exists, but part of it is unproven.`;
    default:
      return `The evidence argues against this ${steps}-step route.`;
  }
}

function conditionsOf(s: S, stepId: string): string | null {
  const step = s.report?.data.steps.find((x) => x.hypothesis_id === stepId);
  const best = step?.precedents?.find((p) => p.outcome === "success");
  if (!best) return null;
  const c = best.conditions ?? {};
  const pretty = (v: unknown) => String(v).replace(/_/g, " ");
  const parts = [c.temperature_c != null ? `${c.temperature_c} °C` : null, c.solvent, c.catalyst, c.time]
    .filter(Boolean).map(pretty);
  if (parts.length) return parts.join(" · ");
  return c.text ? pretty(c.text) : null;
}

function MoleculeChip({ s, id, tag }: { s: S; id: string; tag: string }) {
  const m = s.molecules[id];
  if (!m) return null;
  return (
    <button
      onClick={() => { s.select({ molecule: id, step: null }); s.setTab("graph"); }}
      className="group flex w-[156px] flex-col items-center rounded-card border border-hairline bg-surface p-2
                 text-center transition-colors hover:border-ink/25"
      title="Show in the graph"
    >
      <Structure smiles={m.smiles} width={136} height={92} framed={false} />
      <span className="mt-1 line-clamp-2 text-[12.5px] font-medium leading-snug">{m.name}</span>
      <span className="text-[11.5px] text-muted">{tag}</span>
    </button>
  );
}

/** Shown when a run stopped without an answer. A stopped run is not a
 *  finding about the molecule, and the page says so. */
function Stopped({ s, onRetry }: { s: S; onRetry: (t: string) => void }) {
  const f = failureOf(s)!;
  return (
    <div className="mx-auto max-w-[760px] animate-rise px-6 py-14">
      <div className="flex items-center gap-2 text-[13px] text-muted">
        <CircleAlert size={16} strokeWidth={1.8} style={{ color: TONE.warn.fg }} aria-hidden />
        Run stopped for {s.target}
      </div>
      <h1 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-0.02em]">
        The run stopped before it reached an answer.
      </h1>
      <Card className="mt-6 p-5">
        <div className="text-[14px] leading-relaxed">{readable(f.message, 400)}</div>
        <div className="mt-3 text-[13px] leading-relaxed text-muted">
          {f.retryable
            ? "An outside service didn't respond. That says nothing about your molecule; trying again usually works."
            : "This is not a verdict on the molecule: nothing was concluded about whether it can be made."}
        </div>
      </Card>
      <button className="btn-primary mt-6" onClick={() => onRetry(s.target)}>
        <RotateCcw size={15} strokeWidth={2} aria-hidden /> Try again
      </button>
    </div>
  );
}

function Intro() {
  const points = [
    { icon: Microscope, t: "Structures come from databases", d: "Names are looked up in PubChem; the AI never invents a molecule." },
    { icon: Scale, t: "Verdicts are computed", d: "Two agents argue, but a fixed rule over the evidence decides the label." },
    { icon: BookOpen, t: "Every claim has a source", d: "Each step links back to the patents and papers behind it." },
  ];
  return (
    <div className="mx-auto max-w-[940px] px-6 py-16">
      <div className="label">Literature-grounded synthesis planning</div>
      <h1 className="mt-3 max-w-2xl text-[36px] font-semibold leading-[1.12] tracking-[-0.024em]">
        Can this molecule be made, and how?
      </h1>
      <p className="mt-4 max-w-xl text-[14.5px] leading-relaxed text-muted">
        Name a molecule, even one that has never been made. Orchanium breaks it into possible steps,
        finds published reactions that back each step up, checks the chemistry, and has two agents
        argue over the evidence before it answers.
      </p>
      <div className="mt-8 grid max-w-3xl gap-4 sm:grid-cols-3">
        {points.map(({ icon: Icon, t, d }) => (
          <Card key={t} className="p-4">
            <Icon size={18} strokeWidth={1.6} className="text-accent" aria-hidden />
            <div className="mt-2.5 text-[13.5px] font-medium">{t}</div>
            <div className="mt-1 text-[12.5px] leading-relaxed text-muted">{d}</div>
          </Card>
        ))}
      </div>
      <div className="mt-8 text-[12.5px] text-muted">
        Try <span className="text-ink">ibuprofen</span>, or paste a SMILES for a new compound.
      </div>
    </div>
  );
}

export function ResultView({ onRetry }: { onRetry: (target: string) => void }) {
  const s = useRun();
  const { steps, buy, target } = routeStory(s);
  const v = s.verdict;
  const data = s.report?.data;
  const label = (v?.label ?? "Uncertain") as VerdictLabel;
  const meta = VERDICT[label] ?? VERDICT.Uncertain;
  const tone = TONE[meta.tone];

  if (s.status === "idle" && !steps.length) return <Intro />;
  if (s.status === "failed" && !steps.length) return <Stopped s={s} onRetry={onRetry} />;

  if (!steps.length && s.status === "running") {
    return (
      <div className="mx-auto max-w-[940px] px-6 py-12">
        <div className="label">Working on {targetName(s)}</div>
        <h1 className="mt-3 max-w-xl text-[30px] font-semibold leading-[1.18] tracking-[-0.02em]">
          Looking for published evidence behind each possible step…
        </h1>
        <p className="mt-3 max-w-lg text-muted">
          The answer appears here once every step has been weighed. The Graph tab shows the
          route taking shape in the meantime.
        </p>
      </div>
    );
  }

  if (!steps.length) {
    return (
      <div className="mx-auto max-w-[760px] px-6 py-12">
        <div className="label">Result for {targetName(s)}</div>
        <h1 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-0.02em]">
          No route back to buyable chemicals was found.
        </h1>
        <p className="mt-3 text-muted">
          Every possible step was checked, but none led all the way back to chemicals you can
          buy with published evidence behind it.
          {v?.gaps?.length ? ` Stuck at: ${v.gaps.map((g) => s.molecules[g]?.name ?? g).join(", ")}.` : ""}
        </p>
      </div>
    );
  }

  const objections = data?.debate?.sustained_objections ?? [];
  const thin = steps.filter((x) => x.grade === "weak" || x.grade === "none");
  const sources = new Set(
    Object.values(s.prov).filter((n) => n.node_type === "source").map((n) => n.details?.url ?? n.id),
  ).size;
  const patents = data?.evidence?.clues_by_source?.uspto ?? 0;
  const checks = data?.evidence?.citation_checks ?? {};
  const verified = checks.verified ?? checks.pass ?? 0;

  return (
    <div className="mx-auto max-w-[920px] animate-rise px-6 py-10">
      {/* ---------------------------------------------------------- answer */}
      <div className="label">Result for {targetName(s)}</div>
      <div className="mt-3 grid gap-6 md:grid-cols-[1fr_260px]">
        <div>
          <h1 className="text-[34px] font-semibold leading-[1.14] tracking-[-0.022em]">
            {headline(label, steps.length, buy.length > 0)}
          </h1>
          <p className="mt-3 text-[14px] leading-relaxed text-muted">
            {meta.note}
            {s.blind && " Blind mode was on: every source that mentions this molecule was hidden, so the route was worked out, not looked up."}
          </p>
          <div className="mt-5 flex gap-2">
            <button
              className="btn-secondary"
              disabled={!s.report}
              onClick={() => {
                const blob = new Blob([s.report?.markdown ?? ""], { type: "text/markdown" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `orchanium-${s.targetInfo?.name ?? "route"}.md`;
                a.click();
              }}
            >
              <Download size={15} strokeWidth={1.8} aria-hidden /> Export report
            </button>
            <button
              className="btn-secondary"
              onClick={() => navigator.clipboard.writeText(
                steps.map((x) => `${x.index}. ${x.classes[0] ?? "Step"}: ${x.reaction}`).join("\n"),
              )}
            >
              <Copy size={15} strokeWidth={1.8} aria-hidden /> Copy route
            </button>
          </div>
        </div>

        <Card tone={meta.tone as keyof typeof TONE} className="self-start p-5">
          <div className="flex items-center gap-2">
            {meta.tone === "good"
              ? <ShieldCheck size={20} strokeWidth={1.8} style={{ color: tone.fg }} aria-hidden />
              : <TriangleAlert size={20} strokeWidth={1.8} style={{ color: tone.fg }} aria-hidden />}
            <span className="text-[20px] font-semibold" style={{ color: tone.fg }}>{label}</span>
          </div>
          {v && (
            <>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-hairline">
                <div className="h-full rounded-full" style={{ width: `${v.confidence * 100}%`, background: tone.fg }} />
              </div>
              <div className="mt-1.5 text-[12.5px] text-muted">
                {confidenceWords(v.confidence)} ({Math.round(v.confidence * 100)}%)
              </div>
            </>
          )}
          <div className="mt-3 border-t border-hairline pt-3 text-[12.5px] leading-relaxed text-muted">
            The label comes from a fixed rule over the evidence, not from the AI's opinion.
          </div>
        </Card>
      </div>

      {/* ----------------------------------------------------------- route */}
      <Section
        className="mt-12"
        title="How to make it"
        hint={`${plural(steps.length, "step")}, starting from ${plural(buy.length, "chemical")} you can buy.`}
      >
        <div className="relative">
          {/* start */}
          <TimelineRow icon={<PackageCheck size={16} strokeWidth={1.8} aria-hidden />} title="Start with">
            <div className="flex flex-wrap gap-3">
              {buy.map((id) => <MoleculeChip key={id} s={s} id={id} tag="buy" />)}
            </div>
          </TimelineRow>

          {steps.map((step) => {
            const g = GRADE[step.grade as Grade] ?? GRADE.none;
            const cond = conditionsOf(s, step.id);
            const isLast = step.product === target;
            const newInputs = step.reactants.filter((r) => buy.includes(r) && step.index > 1);
            return (
              <TimelineRow
                key={step.id}
                icon={<span className="text-[12.5px] font-semibold tabular-nums">{step.index}</span>}
                title={`Step ${step.index}`}
              >
                <Card className="p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[15px] font-semibold">{step.classes[0] ?? "Chemical step"}</div>
                      <div className="mt-0.5 text-[13.5px] text-muted">{reactionPlain(step.classes[0])}</div>
                    </div>
                    <GradeBadge grade={step.grade} sources={sourceCount(s, step.id)} />
                  </div>

                  {newInputs.length > 0 && (
                    <div className="mt-3 text-[13px]">
                      <span className="text-muted">Add </span>
                      {newInputs.map((r) => s.molecules[r]?.name ?? r).join(", ")}
                    </div>
                  )}

                  <dl className="mt-3 grid gap-x-6 gap-y-2 text-[13px] sm:grid-cols-[110px_1fr]">
                    <dt className="text-muted">Conditions</dt>
                    <dd>{cond ?? <span className="text-muted">not reported in the sources</span>}</dd>
                    <dt className="text-muted">Evidence</dt>
                    <dd>{g.plain}</dd>
                  </dl>

                  {step.objections.length > 0 && (
                    <button
                      onClick={() => { s.select({ step: step.id }); s.setTab("debate"); }}
                      className="mt-3 flex w-full items-start gap-2 rounded-chip px-3 py-2 text-left text-[13px]
                                 transition-colors hover:brightness-95"
                      style={{ background: TONE.warn.bg, color: TONE.warn.fg }}
                    >
                      <TriangleAlert size={15} strokeWidth={1.8} className="mt-[2px] shrink-0" aria-hidden />
                      <span>Skeptic: {firstClause(step.objections[0].claim, 150)}</span>
                    </button>
                  )}

                  <div className="mt-3 flex justify-end">
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
                    <MoleculeChip s={s} id={step.product} tag={isLast ? "the target" : "made in this step"} />
                  </div>
                )}
              </TimelineRow>
            );
          })}

          <TimelineRow
            icon={<Target size={16} strokeWidth={1.8} aria-hidden />}
            title={`Done: ${targetName(s)}`}
            last
          />
        </div>
      </Section>

      {/* ---------------------------------------------------------- risks */}
      <Section
        className="mt-12"
        title="Before you try it"
        hint="What the Skeptic could not dismiss, and steps with thin evidence."
      >
        <Card className="divide-y divide-hairline">
          {objections.map((o) => (
            <div key={o.id} className="flex gap-3 px-4 py-3.5 text-[13.5px] leading-relaxed">
              <TriangleAlert size={16} strokeWidth={1.8} className="mt-[3px] shrink-0" style={{ color: TONE.warn.fg }} aria-hidden />
              <span><MoreText short={firstSentence(o.claim)} full={readable(o.claim, 2000)} /></span>
            </div>
          ))}
          {thin.map((x) => (
            <div key={x.id} className="flex gap-3 px-4 py-3.5 text-[13.5px] leading-relaxed">
              <FlaskConical size={16} strokeWidth={1.8} className="mt-[3px] shrink-0" style={{ color: TONE.warn.fg }} aria-hidden />
              <span>
                Step {x.index} ({x.classes[0] ?? "step"}) has {x.grade === "none" ? "no published precedent" : "only thin precedent"}.
                Run it at small scale first.
              </span>
            </div>
          ))}
          {!objections.length && !thin.length && (
            <div className="flex gap-3 px-4 py-3.5 text-[13.5px] text-muted">
              <ShieldCheck size={16} strokeWidth={1.8} className="mt-[2px] shrink-0" style={{ color: TONE.good.fg }} aria-hidden />
              No standing objections. Every step is backed by published work.
            </div>
          )}
        </Card>
      </Section>

      {/* ------------------------------------------------------- based on */}
      <Section className="mt-12" title="What this is based on">
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat icon={Library} value={sources} label="sources read" />
          <Stat icon={BookOpen} value={patents} label="patent reactions matched" />
          <Stat icon={FileCheck2} value={verified} label="quotes checked against the source" />
        </div>
        <div className="mt-3 text-[12.5px] text-muted">
          Run cost ${s.cost.usd.toFixed(2)} · {plural(s.cost.searches, "web search", "web searches")}
        </div>
      </Section>
    </div>
  );
}

function TimelineRow({
  icon, title, children, last = false,
}: { icon: ReactNode; title: string; children?: ReactNode; last?: boolean }) {
  return (
    <div className="relative flex gap-4 pb-7">
      {!last && <div className="absolute left-[15px] top-8 bottom-0 w-px bg-hairline" aria-hidden />}
      <div className="z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border border-hairline bg-surface">
        {icon}
      </div>
      <div className="min-w-0 flex-1 pt-1.5">
        <div className="label mb-2.5">{title}</div>
        {children}
      </div>
    </div>
  );
}

function Stat({ icon: Icon, value, label }: { icon: typeof Library; value: number; label: string }) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <Icon size={18} strokeWidth={1.6} className="text-muted" aria-hidden />
      <div>
        <div className="text-[20px] font-semibold tabular-nums leading-none">{value}</div>
        <div className="mt-1 text-[12.5px] text-muted">{label}</div>
      </div>
    </Card>
  );
}
