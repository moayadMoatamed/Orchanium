import { useEffect, useState } from "react";
import { elapsed, useRun } from "../state/runStore";
import { Mono } from "./primitives";

function Logo() {
  return (
    <div className="flex items-center gap-2.5 pr-1">
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden>
        <path
          d="M13 1.6 23 7.3v11.4L13 24.4 3 18.7V7.3z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <circle cx="13" cy="13" r="2.9" fill="currentColor" />
      </svg>
      <span className="text-[17px] font-semibold tracking-[-0.01em]">Orchanium</span>
    </div>
  );
}

function statusLine(s: ReturnType<typeof useRun.getState>, secs: number) {
  const mins = secs >= 60 ? `${Math.floor(secs / 60)} min` : `${Math.round(secs)}s`;
  const sources = Object.values(s.prov).filter((n) => n.node_type === "source").length;
  if (s.status === "running") {
    // the phase is whichever agent spoke last, not whichever started first
    let latest: { label: string; ts: number } | null = null;
    for (const id of s.agentOrder) {
      const a = s.agents[id];
      const last = a?.logs[a.logs.length - 1];
      if (last && (!latest || last.ts > latest.ts)) latest = { label: a.label, ts: last.ts };
    }
    return { live: true, text: `${latest?.label ?? "Working"} · ${sources} sources` };
  }
  if (s.status === "done") return { live: false, text: `Finished · ${mins} · ${sources} sources read` };
  if (s.status === "failed") return { live: false, text: `Stopped · ${mins}` };
  return { live: false, text: "Ready" };
}

export function TopBar({ onRun }: { onRun: (target: string, opts: { blind: boolean }) => void }) {
  const s = useRun();
  const [value, setValue] = useState("ibuprofen");
  const [blind, setBlind] = useState(false);
  const [, tick] = useState(0);

  useEffect(() => {
    if (s.status !== "running") return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [s.status]);

  const st = statusLine(s, elapsed(s));
  const busy = s.status === "running";

  return (
    <header className="sticky top-0 z-20 border-b border-hairline bg-ground/90 backdrop-blur">
      <div className="flex items-center gap-4 px-5 py-3">
        <Logo />
        <form
          className="flex min-w-0 flex-1 items-center gap-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (value.trim() && !busy) onRun(value.trim(), { blind });
          }}
        >
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            spellCheck={false}
            placeholder="Molecule name or SMILES — e.g. ibuprofen, or CC(C)Cc1ccc(C(C)C(=O)O)cc1"
            className="min-w-0 flex-1 rounded-chip border border-hairline bg-surface px-3.5 py-2.5
                       text-[14px] outline-none transition-colors placeholder:text-muted/55
                       focus:border-accent/50 focus:ring-1 focus:ring-accent/20"
          />
          <button type="submit" className="btn-primary shrink-0" disabled={busy || !value.trim()}>
            Find route
          </button>
        </form>

        <label
          title="Blind mode hides any evidence that mentions the target, to prove the route was reasoned out rather than looked up"
          className="hidden shrink-0 cursor-pointer select-none items-center gap-2 text-[12.5px] text-muted lg:flex"
        >
          <input
            type="checkbox"
            checked={blind}
            disabled={busy}
            onChange={(e) => setBlind(e.target.checked)}
            className="accent-accent"
          />
          Blind mode
        </label>

        <div className="flex shrink-0 items-center gap-2 text-[12.5px] text-muted">
          {st.live && <span className="h-[7px] w-[7px] animate-livedot rounded-full bg-accent" />}
          <span>{st.text}</span>
          {s.cost.usd > 0 && <Mono className="hidden xl:inline">· ${s.cost.usd.toFixed(2)}</Mono>}
        </div>
      </div>
    </header>
  );
}
