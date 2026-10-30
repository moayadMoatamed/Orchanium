import { useEffect, useRef, useState } from "react";
import { useRun } from "../state/runStore";
import { C } from "../tokens";

/** A quiet live ticker: what each agent is doing right now. Collapsed by
 *  default so it never competes with the result. */
export function ActivityDock() {
  const s = useRun();
  const [open, setOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const running = s.status === "running";

  const lines = s.agentOrder
    .flatMap((id) => (s.agents[id]?.logs ?? []).map((l) => ({ ...l, agent: s.agents[id].label })))
    .sort((a, b) => a.ts - b.ts)
    .slice(-120);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ block: "end" });
  }, [lines.length, open]);

  const active = s.agentOrder.map((id) => s.agents[id]).filter((a) => a?.status === "running");

  if (!running && !lines.length) return null;

  return (
    <div className="pointer-events-none fixed bottom-0 left-0 right-0 z-30 flex justify-center px-4 pb-4">
      <div className="pointer-events-auto w-full max-w-[940px] overflow-hidden rounded-card border border-hairline
                      bg-surface/95 shadow-[0_1px_3px_rgba(28,27,25,.06)] backdrop-blur">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-3 px-4 py-2.5 text-left"
        >
          {running && <span className="h-[7px] w-[7px] animate-livedot rounded-full" style={{ background: C.accent }} />}
          <span className="text-[12.5px] font-medium">
            {running ? (active[0]?.label ?? "Working") : "Activity"}
          </span>
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted">
            {lines.length ? lines[lines.length - 1].text : "—"}
          </span>
          <span className="shrink-0 text-[11px] text-muted">{open ? "hide" : "show"}</span>
        </button>
        {open && (
          <div className="max-h-[220px] overflow-y-auto border-t border-hairline px-4 py-2.5">
            {lines.map((l, i) => (
              <div key={i} className="flex gap-3 py-[3px] text-[12px] leading-relaxed">
                <span className="w-[120px] shrink-0 truncate text-muted">{l.agent}</span>
                <span
                  className="min-w-0 flex-1"
                  style={{ color: l.level === "error" ? C.rejected : l.level === "warn" ? C.warning : undefined }}
                >
                  {l.text}
                </span>
              </div>
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>
    </div>
  );
}
