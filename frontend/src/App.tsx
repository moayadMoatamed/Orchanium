import { BrainCircuit, FileSearch, History, MessagesSquare, Network, Play, ShieldCheck, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ActivityDock } from "./components/ActivityDock";
import { DebateView } from "./components/DebateView";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { GraphView } from "./components/GraphView";
import { ResultView } from "./components/ResultView";
import { TopBar } from "./components/TopBar";
import { VerificationView } from "./components/VerificationView";
import { useRun, type Tab } from "./state/runStore";

const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "result", label: "Result", icon: FileSearch },
  { id: "graph", label: "Route map", icon: Network },
  { id: "verification", label: "Verification", icon: ShieldCheck },
  { id: "debate", label: "Debate", icon: MessagesSquare },
];

export default function App() {
  const s = useRun();
  const disconnect = useRef<(() => void) | null>(null);
  const [recent, setRecent] = useState<{ id: string; target: string; status: string }[]>([]);
  const [known, setKnown] = useState<{ clues: number; molecules: number; runs: number; by_origin: Record<string, number> } | null>(null);

  useEffect(() => {
    fetch("/api/runs?limit=8")
      .then((r) => r.json())
      .then((rows) => setRecent(rows.map((r: any) => ({ id: r.id, target: r.target, status: r.status }))))
      .catch(() => {});
    fetch("/api/knowledge").then((r) => r.json()).then(setKnown).catch(() => {});
  }, [s.status, s.revisions.length]);

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

  return (
    <div className="flex h-full flex-col">
      <TopBar onRun={start} />

      <div className="flex items-center gap-1 border-b border-hairline px-5 py-2.5">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => s.setTab(id)} className={`tab inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap ${s.tab === id ? "tab-active" : ""}`}>
            <Icon size={15} strokeWidth={1.8} aria-hidden />
            {label}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-3 text-[12.5px] text-muted">
          {s.blind && <span title="Evidence mentioning the target was hidden">blind mode</span>}
          {known && known.clues > 0 && (
            <span
              className="hidden items-center gap-1.5 whitespace-nowrap md:inline-flex"
              title={`Evidence kept from ${known.runs} earlier run(s) and your lab notes, covering ${known.molecules} molecules. `
                + "Every new run starts with whatever bears on its steps."}
            >
              <BrainCircuit size={14} strokeWidth={1.8} aria-hidden />
              {known.clues} clues known
              {known.by_origin.lab ? ` · ${known.by_origin.lab} from your lab` : ""}
            </span>
          )}
          {recent.length > 0 && (
            <label className="flex items-center gap-1.5">
              <History size={14} strokeWidth={1.8} aria-hidden />
              <select
                className="rounded-chip border border-hairline bg-surface px-2 py-1 text-[12.5px] outline-none"
                value={s.runId ?? ""}
                onChange={(e) => e.target.value && open(e.target.value)}
              >
                <option value="">Past runs…</option>
                {recent.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.target.length > 36 ? `${r.target.slice(0, 35)}…` : r.target} · {r.status === "failed" ? "stopped" : r.status}
                  </option>
                ))}
              </select>
            </label>
          )}
          {s.runId && s.status !== "running" && (
            <button className="inline-flex items-center gap-1 hover:text-ink" onClick={() => open(s.runId!, 6)} title="Replay this run at 6× speed">
              <Play size={13} strokeWidth={2} aria-hidden /> Replay
            </button>
          )}
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-hidden">
        <ErrorBoundary name={s.tab} key={s.tab}>
          {s.tab === "result" && (
            <div className="h-full overflow-y-auto pb-28">
              <ResultView onRetry={(t) => start(t, { blind: s.blind })} />
            </div>
          )}
          {s.tab === "graph" && <GraphView />}
          {s.tab === "verification" && <VerificationView />}
          {s.tab === "debate" && <DebateView />}
        </ErrorBoundary>
      </main>

      <ErrorBoundary name="activity">
        <ActivityDock />
      </ErrorBoundary>
    </div>
  );
}
