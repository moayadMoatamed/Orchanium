import { EyeOff, Loader2, Search } from "lucide-react";
import { Logo } from "./Logo";
import { useEffect, useState } from "react";
import { elapsed, useRun } from "../state/runStore";
import { Mono } from "./primitives";

function statusLine(s: ReturnType<typeof useRun.getState>, secs: number) {
  if (s.starting) return { live: true, text: "Starting run…" };
  if (s.startError) return { live: false, text: s.startError };
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
  const busy = s.status === "running" || s.starting;

  return (
    <header className="sticky top-0 z-20 border-b border-hairline bg-ground/90 backdrop-blur">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
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
            {busy
              ? <><Loader2 size={15} strokeWidth={2} className="animate-spin" aria-hidden /> {s.starting ? "Starting…" : "Running…"}</>
              : <><Search size={15} strokeWidth={2} aria-hidden /> Find route</>}
          </button>
        </form>

        {/* A switch, not a labelled button: "Blind mode off" reads either as the
            state or as what pressing it does. The knob's position says which. */}
        <button
          type="button"
          role="switch"
          aria-checked={blind}
          disabled={busy}
          onClick={() => setBlind(!blind)}
          title={blind
            ? "Blind mode is ON. Every source that mentions this molecule is hidden, so the route has to be reasoned out. Turn it off for the best answer."
            : "Blind mode is OFF. Turn it on to hide every source that mentions this molecule and prove the route was reasoned out rather than looked up."}
          className={`inline-flex shrink-0 items-center gap-2 rounded-chip border px-2.5 py-1.5 text-[13px]
                      font-medium transition-colors disabled:opacity-40 ${
            blind ? "border-accent/40 bg-accent/10 text-accent" : "border-hairline text-muted hover:text-ink"}`}
        >
          <span className={`relative h-[16px] w-[28px] shrink-0 rounded-full transition-colors ${
            blind ? "bg-accent" : "bg-ink/25"}`}>
            <span className={`absolute top-[2px] h-3 w-3 rounded-full bg-white shadow-sm transition-all ${
              blind ? "left-[14px]" : "left-[2px]"}`} />
          </span>
          <EyeOff size={14} strokeWidth={1.9} aria-hidden />
          Blind mode
        </button>

        <div className="flex shrink-0 items-center gap-2 text-[12.5px] text-muted">
          {st.live && <span className="h-[7px] w-[7px] animate-livedot rounded-full bg-accent" />}
          <span>{st.text}</span>
          {s.cost.usd > 0 && <Mono className="hidden xl:inline">· ${s.cost.usd.toFixed(2)}</Mono>}
        </div>
      </div>
    </header>
  );
}
