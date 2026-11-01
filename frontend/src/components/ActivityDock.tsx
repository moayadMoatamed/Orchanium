import { ChevronUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRun } from "../state/runStore";
import { readable } from "../textutil";
import { C } from "../tokens";

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

/** A quiet live ticker. Two views: the Meta model calls this run is making,
 *  and what each agent is doing. Collapsed by default so it never competes
 *  with the result. */
export function ActivityDock() {
  const s = useRun();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"meta" | "agents">("meta");
  const endRef = useRef<HTMLDivElement>(null);
  const running = s.status === "running";

  const calls = s.metaCalls;
  const live = calls.filter((c) => !c.cached);
  const spend = live.reduce((a, c) => a + c.usd, 0);

  const lines = s.agentOrder
    .flatMap((id) => (s.agents[id]?.logs ?? []).map((l) => ({
      ...l, text: readable(l.text, 400), agent: readable(s.agents[id].label, 40),
    })))
    .sort((a, b) => a.ts - b.ts)
    .slice(-120);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ block: "end" });
  }, [lines.length, calls.length, open, view]);

  const latestLog = lines[lines.length - 1];
  const latestCall = calls[calls.length - 1];

  if (!running && !lines.length && !calls.length) return null;

  const summary = calls.length
    ? `${live.length} Meta model call${live.length === 1 ? "" : "s"} · $${spend.toFixed(2)}`
    : latestLog?.text ?? "—";

  return (
    <div className="pointer-events-none fixed bottom-0 left-0 right-0 z-30 flex justify-center px-4 pb-4">
      <div className="pointer-events-auto w-full max-w-[940px] overflow-hidden rounded-card border border-hairline
                      bg-surface/95 shadow-[0_1px_3px_rgba(28,27,25,.06)] backdrop-blur">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-3 px-4 py-2.5 text-left"
        >
          {running && <span className="h-[7px] w-[7px] animate-livedot rounded-full" style={{ background: C.accent }} />}
          <span className="shrink-0 text-[12.5px] font-medium">
            {calls.length ? "Meta API" : latestLog?.agent ?? (running ? "Working" : "Activity")}
          </span>
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted">
            {latestCall && running
              ? `${latestCall.model} · ${latestCall.cached ? "cached" : `${latestCall.latency_s.toFixed(2)}s`} — ${summary}`
              : summary}
          </span>
          <ChevronUp
            size={15}
            strokeWidth={1.8}
            className={`shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`}
            aria-label={open ? "Hide activity" : "Show activity"}
          />
        </button>

        {open && (
          <div className="border-t border-hairline">
            <div className="flex items-center gap-1 px-4 pt-2.5">
              {(["meta", "agents"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`rounded-chip px-2.5 py-1 text-[12px] font-medium transition-colors
                              ${view === v ? "bg-hairline/60 text-ink" : "text-muted hover:text-ink"}`}
                >
                  {v === "meta" ? `Meta calls (${calls.length})` : `Agents (${lines.length})`}
                </button>
              ))}
            </div>

            <div className="max-h-[220px] overflow-y-auto px-4 py-2.5">
              {view === "meta" ? (
                calls.length ? (
                  calls.map((c, i) => (
                    <div key={i} className="flex gap-3 py-[3px] font-mono text-[12px] leading-relaxed">
                      <span className="w-[140px] shrink-0 truncate" style={{ color: C.accent }}>{c.model}</span>
                      <span className="w-[108px] shrink-0 truncate text-muted">{c.agent_id ?? "—"}</span>
                      {c.cached ? (
                        <span className="text-muted">cached — no request sent</span>
                      ) : (
                        <>
                          <span className="w-[62px] shrink-0 text-muted">{c.latency_s.toFixed(2)}s</span>
                          <span className="w-[112px] shrink-0 text-muted">
                            {k(c.tokens_in)} → {k(c.tokens_out)}
                          </span>
                          <span className="w-[92px] shrink-0 text-muted">
                            {c.searches ? `${c.searches} search${c.searches === 1 ? "" : "es"}` : ""}
                          </span>
                          <span className="text-muted">${c.usd.toFixed(4)}</span>
                        </>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="py-1 text-[12px] text-muted">No model calls yet.</div>
                )
              ) : (
                lines.map((l, i) => (
                  <div key={i} className="flex gap-3 py-[3px] text-[12px] leading-relaxed">
                    <span className="w-[120px] shrink-0 truncate text-muted">{l.agent}</span>
                    <span
                      className="min-w-0 flex-1"
                      style={{ color: l.level === "error" ? C.rejected : l.level === "warn" ? C.warning : undefined }}
                    >
                      {l.text}
                    </span>
                  </div>
                ))
              )}
              <div ref={endRef} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
