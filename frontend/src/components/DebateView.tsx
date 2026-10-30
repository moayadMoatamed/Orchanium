import { CircleCheck, Hammer, MessagesSquare, ScanSearch, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { routeSteps, useRun } from "../state/runStore";
import type { ProvNode } from "../state/types";
import { firstSentence, plural, readable } from "../textutil";
import { TONE } from "../tokens";
import { Card, Empty, MoreText, Section } from "./primitives";

const SEVERITY: Record<string, { word: string; tone: keyof typeof TONE }> = {
  fail: { word: "serious objection", tone: "bad" },
  warn: { word: "objection", tone: "warn" },
};

function Turn({ t }: { t: ProvNode }) {
  const builder = t.details?.agent === "builder" || t.agent_id === "builder";
  const text = (t.details?.text as string) ?? t.summary;
  const cited = ((t.details?.cited_ids as string[]) ?? []).length;
  const struck = ((t.details?.struck_citations as string[]) ?? []).length;
  const sev = builder ? null : SEVERITY[t.status];
  const Icon = builder ? Hammer : ScanSearch;
  return (
    <div className="flex gap-3 py-3.5">
      <div
        className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-hairline"
        style={{ background: builder ? "#fff" : "#EEEBE4" }}
      >
        <Icon size={15} strokeWidth={1.8} aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 text-[12.5px]">
          <span className="font-medium">{builder ? "Builder" : "Skeptic"}</span>
          {sev && <span style={{ color: TONE[sev.tone].fg }}>raised an {sev.word}</span>}
          {!builder && !sev && <span className="text-muted">had no objection</span>}
          <span className="text-muted">· round {t.details?.turn ?? 1}</span>
        </div>
        <div className="mt-1 text-[13.5px] leading-relaxed">
          <MoreText short={firstSentence(text)} full={readable(text, 4000)} />
        </div>
        {(cited > 0 || struck > 0) && (
          <div className="mt-1.5 text-[12px] text-muted">
            {cited > 0 && `backed by ${plural(cited, "piece")} of evidence from the graph`}
            {struck > 0 && (
              <span style={{ color: TONE.bad.fg }}>
                {cited > 0 && " · "}{plural(struck, "citation")} rejected because it pointed at nothing real
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function DebateView() {
  const s = useRun();
  const steps = routeSteps(s);
  const turns = useMemo(
    () => s.provOrder.map((id) => s.prov[id]).filter((n): n is ProvNode => !!n && n.node_type === "debate"),
    [s.provOrder, s.prov],
  );
  const sustained = s.report?.data.debate?.sustained_objections ?? [];

  if (!turns.length) {
    return (
      <Empty
        icon={MessagesSquare}
        title={s.status === "running" ? "The debate starts once the evidence is in." : "No debate was held for this run."}
        hint="A Builder defends the route with published evidence. A Skeptic tries to break it. Neither can overrule the chemistry checks."
      />
    );
  }

  const isObjection = (t: ProvNode) => t.details?.agent !== "builder" && t.agent_id !== "builder" && !!SEVERITY[t.status];
  const raised = turns.filter(isObjection).length;
  const standing = sustained.length;
  const rounds = Math.max(...turns.map((t) => Number(t.details?.turn ?? 1)));

  const routeIds = new Set(steps.map((x) => x.id));
  const groups = steps.map((step) => ({
    key: step.id,
    title: `Step ${step.index} · ${step.classes[0] ?? "step"}`,
    turns: turns.filter((t) => t.step_id === step.id),
    standing: sustained.filter((o) => o.hypothesis_id === step.id),
  }));
  const other = turns.filter((t) => !t.step_id || !routeIds.has(t.step_id));

  return (
    <div className="h-full overflow-y-auto pb-28">
      <div className="mx-auto max-w-[820px] animate-rise px-6 py-8">
        <div className="label">Adversarial review</div>
        <h1 className="mt-2 text-[28px] font-semibold leading-tight tracking-[-0.02em]">
          {standing
            ? `The route held up, with ${plural(standing, "point")} still open.`
            : "The route held up under scrutiny."}
        </h1>
        <p className="mt-3 text-[14px] leading-relaxed text-muted">
          The Skeptic raised {plural(raised, "objection")} over {plural(rounds, "round")}.{" "}
          {raised - standing > 0 && `The Builder answered ${raised - standing} with evidence. `}
          {standing > 0 ? `${standing} still ${standing === 1 ? "stands" : "stand"}, and ${standing === 1 ? "is" : "are"} listed under "Before you try it" in the result.` : "None of them still stand."}
        </p>

        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          <Card className="flex gap-3 p-4">
            <Hammer size={18} strokeWidth={1.7} className="mt-0.5 shrink-0" aria-hidden />
            <div className="text-[13px] leading-relaxed">
              <div className="font-medium">Builder</div>
              <div className="text-muted">Argues for the route, step by step, citing published reactions.</div>
            </div>
          </Card>
          <Card className="flex gap-3 p-4">
            <ScanSearch size={18} strokeWidth={1.7} className="mt-0.5 shrink-0" aria-hidden />
            <div className="text-[13px] leading-relaxed">
              <div className="font-medium">Skeptic</div>
              <div className="text-muted">Looks for weak comparisons, failure reports and chemistry conflicts.</div>
            </div>
          </Card>
        </div>
        <p className="mt-3 text-[12.5px] text-muted">
          Every claim has to point at real evidence in the graph. Code checks each one, and claims that point at nothing are thrown out.
        </p>

        {groups.filter((g) => g.turns.length).map((g) => (
          <Section
            key={g.key}
            className="mt-9"
            title={g.title}
            action={
              g.standing.length ? (
                <span className="flex items-center gap-1.5 text-[12.5px]" style={{ color: TONE.warn.fg }}>
                  <TriangleAlert size={14} strokeWidth={1.8} aria-hidden /> {plural(g.standing.length, "point")} open
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-[12.5px]" style={{ color: TONE.good.fg }}>
                  <CircleCheck size={14} strokeWidth={1.8} aria-hidden /> settled
                </span>
              )
            }
          >
            <Card
              className="divide-y divide-hairline px-4"
              onClick={() => s.select({ step: g.key })}
              active={s.selectedStep === g.key}
            >
              {g.turns.map((t) => <Turn key={t.id} t={t} />)}
            </Card>
          </Section>
        ))}

        {other.length > 0 && (
          <details className="mt-9">
            <summary className="cursor-pointer text-[13.5px] font-medium">
              Discussion of steps that did not make the final route ({other.length})
            </summary>
            <Card className="mt-3 divide-y divide-hairline px-4">
              {other.map((t) => <Turn key={t.id} t={t} />)}
            </Card>
          </details>
        )}
      </div>
    </div>
  );
}
