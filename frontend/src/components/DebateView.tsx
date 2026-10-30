import { useMemo } from "react";
import { useRun } from "../state/runStore";
import type { ProvNode } from "../state/types";
import { readable } from "../textutil";
import { STATUS_TONE, TONE } from "../tokens";
import { Card, Empty, Label, Pill } from "./primitives";

/** Two agents argue over the graph. Every claim they make cites graph ids,
 *  which code validates — unsupported citations are struck out, not displayed
 *  as fact. */
export function DebateView() {
  const s = useRun();
  const turns = useMemo(
    () =>
      s.provOrder
        .map((id) => s.prov[id])
        .filter((n): n is ProvNode => !!n && n.node_type === "debate"),
    [s.provOrder, s.prov],
  );

  const builder = s.agents["builder"];
  const skeptic = s.agents["skeptic"];
  const sustained = s.report?.data.debate?.sustained_objections ?? [];
  const struck = s.report?.data.debate?.struck_citations ?? [];

  if (!turns.length) {
    return (
      <Empty
        title={s.status === "running" ? "The debate starts once the evidence is in." : "No debate was held."}
        hint="A Builder proposes the route and defends it with evidence. A Skeptic tries to break it. Neither can overrule the chemistry checks."
      />
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[920px] animate-rise px-6 py-8">
        <Label>Adversarial review</Label>
        <h1 className="mt-2 text-[28px] font-semibold leading-tight tracking-[-0.02em]">
          Two agents argued over the evidence.
        </h1>
        <p className="mt-3 max-w-xl text-[14px] leading-relaxed text-muted">
          The Builder proposes the route and defends each step with published precedent. The Skeptic hunts for
          weak analogies, failure reports and chemistry conflicts. Every claim must cite real graph nodes;
          code checks them, and unsupported citations are struck out.
        </p>

        <div className="mt-6 flex flex-wrap gap-2">
          {builder && (
            <Pill tone={builder.status === "failed" ? "bad" : "neutral"}>
              Builder · {builder.status}
            </Pill>
          )}
          {skeptic && (
            <Pill tone={skeptic.status === "failed" ? "bad" : "neutral"}>
              Skeptic · {skeptic.status}
            </Pill>
          )}
          {sustained.length > 0 && (
            <Pill tone="warn">{sustained.length} objection{sustained.length === 1 ? "" : "s"} still standing</Pill>
          )}
          {struck.length > 0 && (
            <Pill tone="bad" title={struck.join(", ")}>{struck.length} citation{struck.length === 1 ? "" : "s"} struck out</Pill>
          )}
        </div>

        <div className="mt-8 space-y-3">
          {turns.map((t) => {
            const isBuilder = t.agent_id === "builder";
            const tone = STATUS_TONE[t.status] ?? "neutral";
            const text = (t.details?.text as string) ?? t.summary;
            const cited = (t.details?.cited_ids as string[]) ?? [];
            const strike = (t.details?.struck_citations as string[]) ?? [];
            return (
              <div key={t.id} className={`flex ${isBuilder ? "justify-start" : "justify-end"}`}>
                <Card
                  className={`max-w-[640px] px-4 py-3.5 ${isBuilder ? "" : "bg-ground/70"}`}
                  onClick={() => t.step_id && s.select({ step: t.step_id })}
                >
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="text-[12.5px] font-medium">
                      {isBuilder ? "🔨 Builder" : "🔍 Skeptic"}
                    </span>
                    <span className="label">round {t.details?.turn ?? ""}</span>
                    {t.status !== "pass" && (
                      <span style={{ color: TONE[tone].fg }} className="text-[12px]">
                        {t.status === "fail" ? "fatal" : t.status === "warn" ? "major" : "minor"}
                      </span>
                    )}
                  </div>
                  <div className="text-[13.5px] leading-relaxed">{readable(text, 1200)}</div>
                  {(cited.length > 0 || strike.length > 0) && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {cited.slice(0, 6).map((c) => (
                        <span
                          key={c}
                          className="rounded-chip border border-hairline px-1.5 py-0.5 font-mono text-[11px] text-muted"
                          title="cited graph node, verified to exist"
                        >
                          {c.length > 22 ? `${c.slice(0, 21)}…` : c}
                        </span>
                      ))}
                      {strike.map((c) => (
                        <span
                          key={c}
                          className="rounded-chip border border-dashed px-1.5 py-0.5 font-mono text-[11px] line-through"
                          style={{ color: TONE.bad.fg, borderColor: TONE.bad.border }}
                          title="cited a node that does not exist — struck out by code"
                        >
                          {c.length > 22 ? `${c.slice(0, 21)}…` : c}
                        </span>
                      ))}
                    </div>
                  )}
                </Card>
              </div>
            );
          })}
        </div>

        {sustained.length > 0 && (
          <Card tone="warn" className="mt-8 p-5">
            <Label className="mb-2">Objections that survived</Label>
            <ul className="space-y-2 text-[13.5px] leading-relaxed">
              {sustained.map((o) => (
                <li key={o.id}>
                  <span className="font-medium">[{o.severity}]</span> {readable(o.claim, 600)}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}
