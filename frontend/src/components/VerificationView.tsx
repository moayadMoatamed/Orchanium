import { ChevronDown, ExternalLink, FileText, Globe, SearchCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { chainForStep, routeSteps, useRun } from "../state/runStore";
import type { ProvNode } from "../state/types";
import { plural, readable } from "../textutil";
import { GRADE, reactionPlain, type Grade } from "../tokens";
import { Card, Empty, GradeBadge, Pill, Section, StatusIcon } from "./primitives";

type S = ReturnType<typeof useRun.getState>;
type Status = "pass" | "warn" | "fail" | "skip";

/** One question a careful reader would ask about a step, answered from the
 *  provenance nodes recorded for it. */
interface Check {
  key: string;
  question: string;
  answer: string;
  status: Status;
  nodes: ProvNode[];
}

const isPatent = (n: ProvNode) => {
  const k = n.details?.kind ?? n.details?.source_type;
  return k === "database" || k === "patent";
};

function checksFor(nodes: ProvNode[]): Check[] {
  const of = (...types: string[]) => nodes.filter((n) => types.includes(n.node_type));
  const sources = of("source");
  const reported = of("extraction");
  const citations = of("citation");
  const structures = of("resolution", "vision");
  const precedents = of("precedent");
  const checks = of("check");

  const patents = sources.filter(isPatent).length;
  const web = sources.length - patents;
  const parts = [patents && plural(patents, "patent"), web && plural(web, "web source")].filter(Boolean);

  const best = precedents.reduce<ProvNode | null>(
    (a, b) => ((b.details?.score ?? 0) > (a?.details?.score ?? -1) ? b : a), null);
  const score = best?.details?.score as number | undefined;
  const alike = Math.round((best?.details?.product_similarity ?? 0) * 100);

  const failures = reported.filter((n) => n.details?.outcome === "failure");
  const quoted = citations.filter((n) => n.status !== "skip");
  const quotedOk = quoted.filter((n) => n.status === "pass").length;
  const checkWarn = checks.filter((n) => n.status === "warn" || n.status === "fail");

  return [
    {
      key: "published",
      question: "Has this reaction been published?",
      status: sources.length ? "pass" : "warn",
      answer: sources.length
        ? `Yes, it appears in ${plural(sources.length, "source")} (${parts.join(", ")}).`
        : "No published source was found for this step.",
      nodes: [...sources, ...reported],
    },
    {
      key: "match",
      question: "How close is the published reaction to ours?",
      status: score == null ? "warn" : score >= 0.55 ? "pass" : "warn",
      answer: score == null
        ? "Nothing close enough to compare."
        : score >= 0.999
          ? "It is the same reaction, on the same molecules."
          : score >= 0.55
            ? `The same kind of reaction on very similar molecules (the product is ${alike}% alike).`
            : `Only loosely similar: the closest product is ${alike}% alike.`,
      nodes: precedents,
    },
    {
      key: "failures",
      question: "Did anyone report it failing?",
      status: failures.length ? "warn" : "pass",
      answer: failures.length
        ? `${plural(failures.length, "source")} reported a failure under some conditions. The Skeptic weighed these.`
        : "No failure reports were found.",
      nodes: failures,
    },
    {
      key: "quotes",
      question: "Do the sources really say this?",
      status: !quoted.length ? "skip" : quotedOk === quoted.length ? "pass" : quotedOk ? "warn" : "warn",
      answer: !quoted.length
        ? "The evidence is structured patent data, so there was no quote to check."
        : quotedOk === quoted.length
          ? `Yes: all ${quoted.length} quoted passages were found on the source page.`
          : `${quotedOk} of ${quoted.length} quoted passages were confirmed. The rest are on pages that block automated reading, so they could not be checked.`,
      nodes: citations,
    },
    {
      key: "structures",
      question: "Are the molecules what we think they are?",
      status: structures.length ? (structures.every((n) => n.status === "pass") ? "pass" : "warn") : "skip",
      answer: structures.length
        ? `${plural(structures.filter((n) => n.status === "pass").length, "structure")} confirmed against PubChem and drawn by RDKit.`
        : "No structure lookups were recorded for this step.",
      nodes: structures,
    },
    {
      key: "chemistry",
      question: "Does the chemistry hold up?",
      status: checks.some((n) => n.status === "fail") ? "fail" : checkWarn.length ? "warn" : checks.length ? "pass" : "skip",
      answer: !checks.length
        ? "No checks were recorded."
        : checkWarn.length
          ? `${plural(checks.length - checkWarn.length, "check")} passed; ${checkWarn.length} raised a note: ${readable(checkWarn[0].summary, 140)}`
          : `All ${plural(checks.length, "check")} passed: no groups that would react with each other, balanced atoms, sensible reagents.`,
      nodes: checks,
    },
  ];
}

function NodeLine({ n }: { n: ProvNode }) {
  const url = n.details?.url as string | undefined;
  return (
    <div className="flex items-start gap-2.5 py-2 text-[13px]">
      <StatusIcon status={n.status} size={14} />
      <div className="min-w-0 flex-1">
        <div className="leading-relaxed">{readable(n.details?.title ?? n.summary, 260)}</div>
        {n.details?.snippet && (
          <div className="mt-1 border-l-2 border-hairline pl-2.5 text-[12.5px] italic text-muted">
            “{readable(n.details.snippet, 280)}”
          </div>
        )}
      </div>
      {url && (
        <a href={url} target="_blank" rel="noreferrer" className="shrink-0 text-muted hover:text-accent" title="Open source">
          <ExternalLink size={14} strokeWidth={1.8} aria-hidden />
        </a>
      )}
    </div>
  );
}

function CheckRow({ c }: { c: Check }) {
  const [open, setOpen] = useState(false);
  const canOpen = c.nodes.length > 0;
  return (
    <div className="border-b border-hairline last:border-0">
      <button
        disabled={!canOpen}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-3 px-4 py-4 text-left enabled:hover:bg-ground/50"
      >
        <span className="mt-[2px]"><StatusIcon status={c.status} size={18} /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-medium">{c.question}</span>
          <span className="mt-0.5 block text-[13.5px] leading-relaxed text-muted">{c.answer}</span>
        </span>
        {canOpen && (
          <ChevronDown
            size={16}
            strokeWidth={1.8}
            className={`mt-1 shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`}
            aria-hidden
          />
        )}
      </button>
      {open && (
        <div className="divide-y divide-hairline/70 px-4 pb-3 pl-[46px]">
          {c.nodes.slice(0, 12).map((n) => <NodeLine key={n.id} n={n} />)}
          {c.nodes.length > 12 && (
            <div className="py-2 text-[12.5px] text-muted">and {c.nodes.length - 12} more</div>
          )}
        </div>
      )}
    </div>
  );
}

function SourceList({ s, nodes }: { s: S; nodes: ProvNode[] }) {
  const sources = nodes.filter((n) => n.node_type === "source");
  const citations = nodes.filter((n) => n.node_type === "citation");
  if (!sources.length) return <div className="text-[13px] text-muted">No sources recorded for this step yet.</div>;
  return (
    <Card className="divide-y divide-hairline">
      {sources.map((n) => {
        const cite = citations.find((c) => c.details?.url && c.details.url === n.details?.url);
        const Icon = isPatent(n) ? FileText : Globe;
        return (
          <a
            key={n.id}
            href={n.details?.url ?? undefined}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-3 px-4 py-3 text-[13.5px] hover:bg-ground/50"
          >
            <Icon size={16} strokeWidth={1.6} className="shrink-0 text-muted" aria-hidden />
            <span className="min-w-0 flex-1 truncate" title={n.details?.title}>
              {n.details?.title ?? readable(n.summary, 120)}
            </span>
            <span className="hidden shrink-0 text-[12px] text-muted sm:inline">
              {isPatent(n) ? "patent" : "web"}
            </span>
            {cite?.status === "pass" && <Pill tone="good">quote confirmed</Pill>}
          </a>
        );
      })}
    </Card>
  );
}

export function VerificationView() {
  const s = useRun();
  const steps = routeSteps(s);
  const stepId = s.selectedStep ?? steps[0]?.id ?? null;
  const step = steps.find((x) => x.id === stepId);
  const nodes = useMemo(() => (stepId ? chainForStep(s, stepId).nodes : []), [s, stepId]);
  const checks = useMemo(() => checksFor(nodes), [nodes]);

  if (!stepId || !step) {
    return (
      <Empty
        icon={SearchCheck}
        title="Why should you trust each step?"
        hint="Once a route is found, this page answers that for every step: who published it, how close it is, whether the quotes are real, and whether the chemistry holds."
      />
    );
  }

  const g = GRADE[step.grade as Grade] ?? GRADE.none;
  const passed = checks.filter((c) => c.status === "pass").length;
  const name = (id: string | null) => (id ? s.molecules[id]?.name ?? id : "");

  return (
    <div className="h-full overflow-y-auto pb-28">
      <div className="mx-auto max-w-[820px] animate-rise px-6 py-8">
        <div className="flex flex-wrap gap-1.5">
          {steps.map((x) => (
            <button
              key={x.id}
              onClick={() => s.select({ step: x.id, node: null })}
              className={`tab ${x.id === stepId ? "tab-active" : ""}`}
            >
              Step {x.index}
            </button>
          ))}
        </div>

        <h1 className="mt-5 text-[28px] font-semibold leading-tight tracking-[-0.02em]">
          {step.classes[0] ?? "Chemical step"}
        </h1>
        <p className="mt-1 text-[14px] text-muted">{reactionPlain(step.classes[0])}.</p>
        <p className="mt-3 text-[13.5px] leading-relaxed">
          {step.reactants.map(name).join(" + ")}
          <span className="mx-2 text-muted">→</span>
          <span className="font-medium">{name(step.product)}</span>
        </p>

        <Card tone={g.tone as "good" | "warn" | "bad"} className="mt-5 flex flex-wrap items-center gap-3 px-4 py-3">
          <GradeBadge grade={step.grade} />
          <span className="text-[13.5px]">{g.plain}</span>
          <span className="ml-auto text-[12.5px] text-muted">{passed} of {checks.length} checks passed</span>
        </Card>

        <Section className="mt-8" title="The checks" hint="Click a check to see the evidence behind it.">
          <Card>{checks.map((c) => <CheckRow key={c.key} c={c} />)}</Card>
        </Section>

        <Section className="mt-10" title="Sources">
          <SourceList s={s} nodes={nodes} />
        </Section>
      </div>
    </div>
  );
}
