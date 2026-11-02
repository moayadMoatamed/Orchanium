import type { ReactNode } from "react";
import {
  EyeOff,
  ArrowRight, BookOpen, BrainCircuit, CircleAlert, Copy, Download, FileCheck2, FlaskConical, Library,
  Microscope, PackageCheck, RotateCcw, Scale, ShieldAlert, ShieldCheck, Target, TriangleAlert,
} from "lucide-react";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { elapsed, failureOf, routeStory, stepCount, targetName, useRun } from "../state/runStore";
import type { Revision } from "../state/types";
import { firstSentence, plural, readable } from "../textutil";
import { TONE, VERDICT, confidenceWords, type VerdictLabel } from "../tokens";
import { Card, MoreText, Section } from "./primitives";
import { MoleculeChip, RouteStepRow, stepTitle } from "./StepCard";

type S = ReturnType<typeof useRun.getState>;

/** "an 8-step", "an 11-step", "a 3-step": numbers read aloud starting with a vowel sound. */
const article = (n: number) => (/^8/.test(String(n)) || n === 11 || n === 18 ? "An" : "A");

function headline(label: string, n: number, buyable: boolean) {
  if (!n) return "No route could be assembled.";
  const steps = plural(n, "step");
  const from = buyable ? " from chemicals you can buy" : "";
  switch (label) {
    case "Feasible":
      return `Can be made in ${steps}${from}.`;
    case "Plausible":
      return `${article(n)} credible ${n}-step route${from}.`;
    case "Uncertain":
      return `${article(n)} ${n}-step route exists, but part of it is unproven.`;
    default:
      return `The evidence argues against this ${n}-step route.`;
  }
}

/** How the step count breaks down, when protection makes it differ from
 *  the number of bond-forming reactions. */
function countHint(c: ReturnType<typeof stepCount>, buy: number) {
  const base = `starting from ${plural(buy, "chemical")} you can buy`;
  if (c.total === c.reactions) return `${plural(c.reactions, "step")}, ${base}.`;
  return `${plural(c.reactions, "bond-forming reaction")} plus ${plural(c.protection, "protection or deprotection step")}, ${base}.`;
}

/** Why the verdict came out this way, in the run's own terms. The canned note
 *  per label was misleading whenever the real problem was something else: a
 *  route whose only missing piece is an unobtainable starting material was
 *  still told it had "a step that has never been shown to work". */
function whyThisLabel(s: S, label: VerdictLabel): string {
  const gaps = s.report?.data.verdict.gaps ?? [];
  if (gaps.length) {
    const names = gaps.map((g) => shortName(g)).join(", ");
    return `Every step is accounted for, but ${plural(gaps.length, "ingredient")} cannot be bought `
      + `or made by this route: ${names}. Until that is solved, the route cannot be run as written.`;
  }
  const reason = s.report?.data.verdict.reasons?.[0];
  if (reason) return firstSentence(reason).replace(/^\w/, (c) => c.toUpperCase()) + ".";
  return VERDICT[label].note;
}

const shortName = (n: string) => (n.length > 48 ? `${n.slice(0, 46)}…` : n);

function Revisions({ revisions }: { revisions: Revision[] }) {
  const latest = revisions[revisions.length - 1];
  return (
    <Card className="mt-6 p-4" tone="lab">
      <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.08em]"
           style={{ color: TONE.lab.fg }}>
        <FlaskConical size={13} strokeWidth={2} aria-hidden />
        Revised by {plural(revisions.length, "lab note")}
      </div>
      <div className="mt-2 flex items-center gap-2 text-[14px]">
        <span className="text-muted">Before your notes: {revisions[0].before.label}</span>
        <ArrowRight size={14} className="text-muted" aria-hidden />
        <span className="font-medium">Now: {latest.after.label}</span>
      </div>
      <ul className="mt-2 space-y-1 text-[13.5px] leading-relaxed">
        {latest.changes.map((c, i) => <li key={i} className="flex gap-2"><span className="text-muted">·</span>{c}</li>)}
      </ul>
      {revisions.length > 1 && (
        <details className="mt-2 text-[12.5px] text-muted">
          <summary className="cursor-pointer">Earlier notes</summary>
          {revisions.slice(0, -1).reverse().map((r) => (
            <div key={r.note_id} className="mt-1.5">{r.before.label} → {r.after.label}: {r.changes.join(" ")}</div>
          ))}
        </details>
      )}
    </Card>
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
    { icon: BrainCircuit, t: "It learns as you use it", d: "Evidence and your lab results are kept, so each run starts knowing more." },
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
      <div className="mt-8 grid max-w-4xl gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {points.map(({ icon: Icon, t, d }) => (
          <Card key={t} className="p-4">
            <Icon size={18} strokeWidth={1.6} className="text-accent" aria-hidden />
            <div className="mt-2.5 text-[13.5px] font-medium">{t}</div>
            <div className="mt-1 text-[12.5px] leading-relaxed text-muted">{d}</div>
          </Card>
        ))}
      </div>
      <Card className="mt-6 flex max-w-4xl items-start gap-3 p-4">
        <EyeOff size={18} strokeWidth={1.6} className="mt-0.5 shrink-0 text-accent" aria-hidden />
        <div>
          <div className="text-[13.5px] font-medium">Proof that it reasons: Blind mode</div>
          <div className="mt-1 text-[12.5px] leading-relaxed text-muted">
            Turn on <span className="text-ink">Blind mode</span> next to the search box and every patent or paper that
            mentions your molecule is hidden. Orchanium then has to build the route from other, related reactions,
            the same way it handles a compound nobody has made yet. Try it on a known drug and compare.
          </div>
        </div>
      </Card>
      <div className="mt-8 text-[12.5px] text-muted">
        Try <span className="text-ink">ibuprofen</span>, or paste a SMILES for a new compound.
      </div>
    </div>
  );
}

/** Shown from the click until the first route appears: a run takes minutes,
 *  so it says what is happening now and keeps moving. */
function Working({ s }: { s: ReturnType<typeof useRun.getState> }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  let phase = s.starting ? "Resolving the molecule" : "Starting the agents";
  let latest = 0;
  for (const id of s.agentOrder) {
    const a = s.agents[id];
    const last = a?.logs[a.logs.length - 1];
    if (last && last.ts > latest) { latest = last.ts; phase = `${a.label}: ${last.text}`; }
  }
  const secs = s.starting ? 0 : Math.max(0, Math.round(elapsed(s)));
  const time = secs >= 60 ? `${Math.floor(secs / 60)} min ${secs % 60}s` : `${secs}s`;
  return (
    <div className="mx-auto max-w-[940px] px-6 py-12">
      <div className="label">Working on {s.target || targetName(s)}</div>
      <h1 className="mt-3 max-w-xl text-[30px] font-semibold leading-[1.18] tracking-[-0.02em]">
        Looking for published evidence behind each possible step…
      </h1>
      <p className="mt-3 max-w-lg text-muted">
        A run usually takes 5–10 minutes. The answer appears here once every step has been
        weighed; the Route map shows the route taking shape in the meantime.
      </p>
      <div className="mt-7 max-w-xl">
        <div className="flex items-center gap-2.5 text-[13.5px]">
          <Loader2 size={16} strokeWidth={2} className="shrink-0 animate-spin text-accent" aria-hidden />
          <span className="min-w-0 truncate">{phase}</span>
          <span className="ml-auto shrink-0 font-mono text-[12px] text-muted">{time}</span>
        </div>
        <div className="mt-3 h-[3px] overflow-hidden rounded-full bg-ink/10">
          <div className="h-full w-1/3 animate-progress rounded-full bg-accent" />
        </div>
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

  if (s.starting) return <Working s={s} />;
  if (s.status === "idle" && !steps.length) return <Intro />;
  if (s.status === "failed" && !steps.length) return <Stopped s={s} onRetry={onRetry} />;

  if (!steps.length && s.status === "running") return <Working s={s} />;

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
  const unguarded = steps.filter((x) => x.detail?.competing_groups && !x.detail.procedure?.some((o) => o.kind === "protect"));
  const count = stepCount(steps);
  const labFailed = steps.filter((x) => (x.detail?.lab_failures ?? 0) > 0 && !(x.detail?.lab_successes ?? 0));
  // lab notes need the run's saved graph, which runs with conditions records have
  const recalled = data?.evidence?.recalled ?? 0;
  const labNotes = steps.reduce((n, x) => n + (x.detail?.lab_notes?.length ?? 0), 0);
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
            {headline(label, count.total, buy.length > 0)}
          </h1>
          <p className="mt-3 text-[14px] leading-relaxed text-muted">
            {labFailed.length
              ? `Step ${labFailed.map((x) => x.index).join(" and ")} failed in your lab, so it needs different conditions or a different approach.`
              : whyThisLabel(s, label)}
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
                steps.map((x) => [`${x.index}. ${stepTitle(s, x)}: ${x.reaction}`,
                  ...(x.detail?.procedure ?? []).map((o, i) => `   ${x.index}.${i + 1} ${o.action}`)].join("\n")).join("\n"),
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
                {confidenceWords(v.confidence, label)} ({Math.round(v.confidence * 100)}%)
              </div>
            </>
          )}
          <div className="mt-3 border-t border-hairline pt-3 text-[12.5px] leading-relaxed text-muted">
            The label comes from a fixed rule over the evidence, not from the AI's opinion.
          </div>
        </Card>
      </div>

      {s.revisions.length > 0 && <Revisions revisions={s.revisions} />}

      {/* ----------------------------------------------------------- route */}
      <Section
        className="mt-12"
        title="How to make it"
        hint={countHint(count, buy.length)}
      >
        <div className="relative">
          {/* start */}
          <TimelineRow icon={<PackageCheck size={16} strokeWidth={1.8} aria-hidden />} title="Start with">
            <div className="flex flex-wrap gap-3">
              {buy.map((id) => <MoleculeChip key={id} s={s} id={id} tag="buy" />)}
            </div>
          </TimelineRow>

          {steps.map((step) => (
            <TimelineRow
              key={step.id}
              icon={<span className="text-[12.5px] font-semibold tabular-nums">{step.index}</span>}
              title={`Step ${step.index}`}
            >
              <RouteStepRow s={s} step={step} target={target} />
            </TimelineRow>
          ))}

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
          {objections.map((o) => {
            const at = steps.find((x) => x.id === o.hypothesis_id);
            return (
              <div key={o.id} className="flex gap-3 px-4 py-3.5 text-[13.5px] leading-relaxed">
                <TriangleAlert size={16} strokeWidth={1.8} className="mt-[3px] shrink-0" style={{ color: TONE.warn.fg }} aria-hidden />
                <div className="min-w-0">
                  {at && <span className="text-muted">Step {at.index}: </span>}
                  {o.plain ? readable(o.plain, 400) : <MoreText short={firstSentence(o.claim)} full={readable(o.claim, 2000)} />}
                  {o.plain && (
                    <details className="mt-1 text-[12.5px] text-muted">
                      <summary className="cursor-pointer">Technical detail</summary>
                      <div className="mt-1">{readable(o.claim, 2000)}</div>
                    </details>
                  )}
                </div>
              </div>
            );
          })}
          {unguarded.map((x) => (
            <div key={`fg-${x.id}`} className="flex gap-3 px-4 py-3.5 text-[13.5px] leading-relaxed">
              <ShieldAlert size={16} strokeWidth={1.8} className="mt-[3px] shrink-0" style={{ color: TONE.warn.fg }} aria-hidden />
              <span>
                Step {x.index}: a reactant has a second group that could react in the wrong place, and no
                protection is planned. Expect side products, or protect it first.
              </span>
            </div>
          ))}
          {thin.map((x) => (
            <div key={x.id} className="flex gap-3 px-4 py-3.5 text-[13.5px] leading-relaxed">
              <FlaskConical size={16} strokeWidth={1.8} className="mt-[3px] shrink-0" style={{ color: TONE.warn.fg }} aria-hidden />
              <span>
                Step {x.index} ({stepTitle(s, x)}) has {x.grade === "none" ? "no published precedent" : "only thin precedent"}.
                Run it at small scale first.
              </span>
            </div>
          ))}
          {!objections.length && !thin.length && !unguarded.length && (
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
          {recalled > 0 && <Stat icon={BrainCircuit} value={recalled} label="clues remembered from earlier runs" />}
          {labNotes > 0 && <Stat icon={FlaskConical} value={labNotes} label="results from your lab" />}
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
