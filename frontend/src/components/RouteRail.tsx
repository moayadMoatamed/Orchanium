import { routeSteps, sourceCount, useRun } from "../state/runStore";
import { GRADE, TONE, type Grade } from "../tokens";

/** Left rail: the chosen route as numbered steps. Clicking a step focuses it
 *  everywhere else in the app. */
export function RouteRail() {
  const s = useRun();
  const steps = routeSteps(s);
  const selected = s.selectedStep;
  const running = s.status === "running";

  const pending = running && steps.length === 0;
  const hypotheses = Object.values(s.reactions).filter((r) => r.kind === "hypothesis");

  return (
    <aside className="hidden w-[248px] shrink-0 overflow-y-auto border-r border-hairline px-4 py-5 lg:block">
      <div className="label mb-3">
        {steps.length ? `Best route · ${steps.length} step${steps.length === 1 ? "" : "s"}` : "Route"}
      </div>

      {pending && (
        <div className="space-y-3">
          {hypotheses.slice(0, 4).map((h) => (
            <div key={h.id} className="flex items-start gap-2.5 opacity-60">
              <span className="mt-0.5 h-[22px] w-[22px] shrink-0 rounded-full border border-dashed border-accent/60" />
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium">{h.classes[0] ?? "Candidate step"}</div>
                <div className="text-[12px] text-muted">Checking…</div>
              </div>
            </div>
          ))}
          {!hypotheses.length && <div className="text-[12.5px] text-muted">Working out candidate steps…</div>}
        </div>
      )}

      <ol className="space-y-1">
        {steps.map((step) => {
          const g = GRADE[step.grade as Grade] ?? GRADE.none;
          const tone = TONE[g.tone as keyof typeof TONE];
          const active = selected === step.id;
          return (
            <li key={step.id}>
              <button
                onClick={() => s.select({ step: active ? null : step.id })}
                className={`flex w-full items-start gap-2.5 rounded-chip px-2 py-2 text-left transition-colors
                  ${active ? "bg-hairline/50" : "hover:bg-hairline/30"}`}
              >
                <span
                  className="mt-[1px] grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full
                             border text-[11.5px] font-medium"
                  style={{ borderColor: tone.border, color: tone.fg }}
                >
                  {step.index}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-medium">
                    {step.classes[0] ?? "Step"}
                  </span>
                  <span className="block text-[12px]" style={{ color: tone.fg }}>
                    {g.label}
                    <span className="text-muted"> · {sourceCount(s, step.id)} sources</span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {s.verdict?.gaps?.length ? (
        <div className="mt-5 border-t border-hairline pt-4">
          <div className="label mb-2">Unsolved</div>
          {s.verdict.gaps.map((g) => (
            <div key={g} className="truncate text-[12.5px] text-muted" title={s.molecules[g]?.name}>
              {s.molecules[g]?.name ?? g}
            </div>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
