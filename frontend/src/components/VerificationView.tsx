import { useMemo } from "react";
import { chainForStep, routeSteps, useRun } from "../state/runStore";
import type { ProvNode } from "../state/types";
import { C, GRADE, STATUS_TONE, TONE, type Grade } from "../tokens";
import { Card, Label, Mono, Pill } from "./primitives";

/** The chain is grouped into the stages a reader actually follows, so one step
 *  reads left to right: what was searched → what was found → was the quote real
 *  → are the structures right → how close is the precedent → does the chemistry
 *  hold → verdict. */
const STAGES: { key: string; title: string; types: string[] }[] = [
  { key: "sources", title: "Sources", types: ["query", "source"] },
  { key: "reported", title: "Reported reaction", types: ["extraction"] },
  { key: "citation", title: "Citation check", types: ["citation"] },
  { key: "structures", title: "Structures", types: ["resolution", "vision"] },
  { key: "precedent", title: "Precedent match", types: ["precedent"] },
  { key: "checks", title: "Chemistry checks", types: ["check"] },
];

function worst(nodes: ProvNode[]): string {
  if (nodes.some((n) => n.status === "fail")) return "fail";
  if (nodes.some((n) => n.status === "warn")) return "warn";
  if (nodes.some((n) => n.status === "pass")) return "pass";
  return "skip";
}

function stageSummary(key: string, nodes: ProvNode[], s: ReturnType<typeof useRun.getState>) {
  switch (key) {
    case "sources": {
      const srcs = nodes.filter((n) => n.node_type === "source");
      const kinds = new Map<string, number>();
      for (const n of srcs) {
        const k = n.details?.kind ?? n.details?.source_type ?? "web";
        kinds.set(k, (kinds.get(k) ?? 0) + 1);
      }
      return {
        big: String(srcs.length),
        sub: [...kinds.entries()].map(([k, n]) => `${n} ${k}${n === 1 ? "" : "s"}`).join(", ") || "none yet",
      };
    }
    case "reported": {
      const n = nodes[0];
      const c = n?.details?.conditions ?? {};
      const parts = [c.temperature_c != null ? `${c.temperature_c} °C` : null, c.solvent, c.catalyst, c.time]
        .filter(Boolean).join(", ");
      const fails = nodes.filter((x) => x.details?.outcome === "failure").length;
      return {
        big: nodes.length ? `${nodes.length} reaction${nodes.length === 1 ? "" : "s"}` : "—",
        sub: fails ? `${fails} reported as failures` : parts || "conditions not stated",
      };
    }
    case "citation": {
      const pass = nodes.filter((n) => n.status === "pass").length;
      const skip = nodes.filter((n) => n.status === "skip").length;
      return {
        big: nodes.length ? `${pass}/${nodes.length - skip || nodes.length} verified` : "—",
        sub: skip ? `${skip} structured records (no quote to check)` : "quotes matched on the page",
      };
    }
    case "structures": {
      const ok = nodes.filter((n) => n.status === "pass").length;
      return { big: ok ? `${ok} confirmed` : "—", sub: "resolved in PubChem, drawn by RDKit" };
    }
    case "precedent": {
      const best = nodes.reduce((a, b) => ((b.details?.score ?? 0) > (a?.details?.score ?? 0) ? b : a), nodes[0]);
      const sc = best?.details?.score;
      return {
        big: sc != null ? sc.toFixed(2) : "—",
        sub: sc != null
          ? `product ${Math.round((best.details.product_similarity ?? 0) * 100)}% similar · change ${Math.round(
              (best.details.transformation_similarity ?? 0) * 100,
            )}% similar`
          : "no precedent found",
      };
    }
    case "checks": {
      const pass = nodes.filter((n) => n.status === "pass").length;
      const warn = nodes.filter((n) => n.status === "warn");
      return {
        big: `${pass} passed`,
        sub: warn.length ? `${warn.length} note: ${warn[0].details?.check ?? ""}` : "no conflicts found",
      };
    }
    default:
      return { big: String(nodes.length), sub: "" };
  }
}

function StageCard({
  title, index, nodes, summary, onClick, active,
}: {
  title: string; index: number; nodes: ProvNode[];
  summary: { big: string; sub: string }; onClick: () => void; active: boolean;
}) {
  const st = worst(nodes);
  const tone = TONE[STATUS_TONE[st] ?? "neutral"];
  const empty = !nodes.length;
  return (
    <Card
      onClick={onClick}
      active={active}
      className={`min-w-[196px] flex-1 px-4 py-3.5 ${empty ? "opacity-45" : ""}`}
    >
      <div className="label mb-2 flex items-center gap-1.5">
        <span className="tabular-nums">{index} ·</span> {title}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-[17px] font-semibold leading-tight">{summary.big}</span>
        {!empty && st !== "pass" && st !== "skip" && (
          <span style={{ color: tone.fg }} className="text-[13px]">
            {st === "fail" ? "×" : "!"}
          </span>
        )}
      </div>
      <div className="mt-1 text-[12.5px] leading-snug text-muted">{summary.sub}</div>
    </Card>
  );
}

export function VerificationView() {
  const s = useRun();
  const steps = routeSteps(s);
  const stepId = s.selectedStep ?? steps[0]?.id ?? null;
  const step = steps.find((x) => x.id === stepId);
  const { nodes } = useMemo(() => (stepId ? chainForStep(s, stepId) : { nodes: [] as ProvNode[] }), [s, stepId]);

  const stages = useMemo(
    () => STAGES.map((st) => ({ ...st, nodes: nodes.filter((n) => st.types.includes(n.node_type)) })),
    [nodes],
  );

  const detail = s.selectedNode ? s.prov[s.selectedNode] : null;
  const sources = nodes.filter((n) => n.node_type === "source");
  const ruledOut = Object.values(s.reactions).filter(
    (r) => r.kind === "hypothesis" && r.critic === "block" && r.products[0] === s.reactions[stepId ?? ""]?.products[0],
  );

  if (!stepId || !step) {
    return (
      <div className="grid h-full place-items-center px-6 text-center">
        <div className="max-w-sm text-[13.5px] text-muted">
          The verification chain traces every step back to the evidence behind it. It fills in as the run proceeds.
        </div>
      </div>
    );
  }

  const g = GRADE[step.grade as Grade] ?? GRADE.none;
  const verdictNode = s.prov[`verdict:${stepId}`];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1080px] animate-rise px-6 py-8">
        <div className="text-[12.5px] text-muted">
          Step {step.index} of {steps.length}
        </div>
        <h1 className="mt-1.5 text-[30px] font-semibold leading-tight tracking-[-0.02em]">
          {step.classes[0] ?? "Step"}
        </h1>
        <div className="mt-1.5 text-[14px] text-muted">{step.reaction}</div>

        {/* the chain */}
        <div className="mt-7 flex flex-wrap items-stretch gap-0">
          {stages.map((st, i) => (
            <div key={st.key} className="flex min-w-[196px] flex-1 items-stretch">
              <StageCard
                index={i + 1}
                title={st.title}
                nodes={st.nodes}
                summary={stageSummary(st.key, st.nodes, s)}
                active={!!detail && st.nodes.some((n) => n.id === detail.id)}
                onClick={() => s.select({ node: st.nodes[0]?.id ?? null })}
              />
              {i < stages.length - 1 && (
                <div className="flex w-5 items-center" aria-hidden>
                  <div className="h-px w-full" style={{ background: C.hairline }} />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* verdict */}
        <Card tone={g.tone as keyof typeof TONE} className="mt-5 inline-block min-w-[260px] px-5 py-4">
          <Label className="mb-1.5">Verdict</Label>
          <div className="text-[18px] font-semibold" style={{ color: TONE[g.tone as keyof typeof TONE].fg }}>
            {g.label}
          </div>
          <div className="mt-1 text-[12.5px] text-muted">
            {verdictNode?.summary ?? g.blurb}
          </div>
          {step.objections.length > 0 && (
            <div className="mt-2 text-[12.5px]" style={{ color: TONE.warn.fg }}>
              {step.objections.length} standing objection{step.objections.length === 1 ? "" : "s"} from the Skeptic
            </div>
          )}
        </Card>

        {/* node detail */}
        {detail && (
          <Card className="mt-6 p-5">
            <div className="mb-2 flex items-center justify-between gap-4">
              <Label>{detail.node_type} · {detail.agent_id ?? ""}</Label>
              <button className="text-[12.5px] text-muted hover:text-ink" onClick={() => s.select({ node: null })}>
                close
              </button>
            </div>
            <div className="text-[14px] leading-relaxed">{detail.summary}</div>
            {detail.details?.method && (
              <div className="mt-2 text-[12.5px] text-muted">{detail.details.method}</div>
            )}
            {detail.details?.snippet && (
              <blockquote className="mt-3 border-l-2 border-hairline pl-3 text-[13px] italic text-muted">
                “{detail.details.snippet}”
              </blockquote>
            )}
            {detail.details?.url && (
              <a
                href={detail.details.url}
                target="_blank"
                rel="noreferrer"
                className="mt-3 inline-block text-[12.5px] text-accent underline decoration-accent/30 underline-offset-4"
              >
                open source
              </a>
            )}
            <details className="mt-4">
              <summary className="cursor-pointer text-[12px] text-muted hover:text-ink">raw data</summary>
              <pre className="mono mt-2 max-h-56 overflow-auto rounded-chip bg-ground p-3 text-[11.5px] leading-relaxed">
                {JSON.stringify(detail.details, null, 1)}
              </pre>
            </details>
          </Card>
        )}

        {/* sources */}
        <Label className="mb-3 mt-8">Sources</Label>
        <div>
          {sources.length ? (
            sources.map((n) => {
              const cite = nodes.find(
                (c) => c.node_type === "citation" && c.details?.url && c.details.url === n.details?.url,
              );
              return (
                <div
                  key={n.id}
                  className="flex items-start gap-4 border-b border-hairline py-3 text-[13.5px] last:border-0"
                >
                  <span className="w-[64px] shrink-0 text-muted">{n.details?.kind ?? "web"}</span>
                  <a
                    href={n.details?.url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="min-w-0 flex-1 truncate hover:text-accent"
                    title={n.details?.title}
                  >
                    {n.details?.title ?? n.summary}
                  </a>
                  {cite && (
                    <Pill tone={STATUS_TONE[cite.status] as keyof typeof TONE} title={cite.summary}>
                      {cite.status === "pass" ? "quote verified" : cite.status === "skip" ? "record" : "unverified"}
                    </Pill>
                  )}
                </div>
              );
            })
          ) : (
            <div className="text-[13px] text-muted">No sources recorded for this step yet.</div>
          )}
        </div>

        {ruledOut.length > 0 && (
          <div className="mt-6 flex items-start gap-2.5 text-[12.5px] text-muted">
            <span className="mt-[6px] h-[5px] w-[5px] shrink-0 rounded-full" style={{ background: C.rejected }} />
            <span>
              Ruled out for the same product:{" "}
              {ruledOut.map((r) => r.classes[0] ?? "alternative").join(", ")} — failed a chemistry check.
            </span>
          </div>
        )}

        <Mono className="mt-8 block">
          {nodes.length} provenance nodes recorded for this step
        </Mono>
      </div>
    </div>
  );
}
