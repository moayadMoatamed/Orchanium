import { useEffect, useRef, useState } from "react";
import { ActivityDock } from "./components/ActivityDock";
import { DebateView } from "./components/DebateView";
import { GraphView } from "./components/GraphView";
import { ResultView } from "./components/ResultView";
import { RouteRail } from "./components/RouteRail";
import { TopBar } from "./components/TopBar";
import { VerificationView } from "./components/VerificationView";
import { useRun, type Tab } from "./state/runStore";

const TABS: { id: Tab; label: string }[] = [
  { id: "result", label: "Result" },
  { id: "graph", label: "Graph" },
  { id: "verification", label: "Verification" },
  { id: "debate", label: "Debate" },
];

export default function App() {
  const s = useRun();
  const disconnect = useRef<(() => void) | null>(null);
  const [recent, setRecent] = useState<{ id: string; target: string; status: string }[]>([]);

  useEffect(() => {
    fetch("/api/runs?limit=8")
      .then((r) => r.json())
      .then((rows) => setRecent(rows.map((r: any) => ({ id: r.id, target: r.target, status: r.status }))))
      .catch(() => {});
  }, [s.status]);

  async function start(target: string, opts: { blind: boolean }) {
    disconnect.current?.();
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, blind: opts.blind }),
    });
    const { run_id } = await res.json();
    useRun.getState().reset(run_id, target);
    disconnect.current = useRun.getState().connect(run_id);
  }

  function open(runId: string, replaySpeed = 0) {
    disconnect.current?.();
    useRun.getState().reset(runId, "");
    disconnect.current = useRun.getState().connect(runId, replaySpeed);
  }

  useEffect(() => () => disconnect.current?.(), []);

  const withRail = s.tab !== "result";

  return (
    <div className="flex h-full flex-col">
      <TopBar onRun={start} />

      <div className="flex items-center gap-1 border-b border-hairline px-5 py-2.5">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => s.setTab(t.id)}
            className={`tab ${s.tab === t.id ? "tab-active" : ""}`}
          >
            {t.label}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2 text-[12.5px] text-muted">
          {s.blind && <span title="Evidence mentioning the target was discarded">blind mode</span>}
          {recent.length > 0 && (
            <select
              className="rounded-chip border border-hairline bg-surface px-2 py-1 text-[12.5px] outline-none"
              value={s.runId ?? ""}
              onChange={(e) => e.target.value && open(e.target.value)}
            >
              <option value="">Past runs…</option>
              {recent.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.target.length > 36 ? `${r.target.slice(0, 35)}…` : r.target} · {r.status}
                </option>
              ))}
            </select>
          )}
          {s.runId && s.status !== "running" && (
            <button className="hover:text-ink" onClick={() => open(s.runId!, 6)} title="Replay this run at 6× speed">
              replay
            </button>
          )}
        </div>
      </div>

      <main className="flex min-h-0 flex-1">
        {withRail && <RouteRail />}
        <div className="min-w-0 flex-1 overflow-hidden">
          {s.tab === "result" && (
            <div className="h-full overflow-y-auto pb-24">
              <ResultView />
            </div>
          )}
          {s.tab === "graph" && <GraphView />}
          {s.tab === "verification" && <VerificationView />}
          {s.tab === "debate" && <DebateView />}
        </div>
      </main>

      <ActivityDock />
    </div>
  );
}
