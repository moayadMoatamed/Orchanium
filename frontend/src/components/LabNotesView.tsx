import { ArrowRight, CircleCheck, CircleX, FlaskConical } from "lucide-react";
import { useState } from "react";
import { routeSteps, useRun } from "../state/runStore";
import { TONE } from "../tokens";
import { LabNoteDialog } from "./LabNoteDialog";
import { Card, Section } from "./primitives";
import { stepTitle, type Step } from "./StepCard";

/** What happened when you actually ran it. A note here outranks every
 *  published source for that step, and the answer is recomputed in front of
 *  you by the same fixed rule. */
export function LabNotesView() {
  const s = useRun();
  const steps = routeSteps(s);
  const [noting, setNoting] = useState<Step | null>(null);
  const ready = s.status === "done" && !!s.report?.data.steps?.[0]?.conditions;

  if (!steps.length) {
    return (
      <Empty title="No route yet"
             body="Run a molecule first. Once there is a route, you can record what happened when you ran each step." />
    );
  }

  return (
    <div className="mx-auto max-w-[940px] px-6 py-10">
      <div className="label">Lab notes</div>
      <h1 className="mt-3 max-w-2xl text-[30px] font-semibold leading-[1.15] tracking-[-0.02em]">
        What happened when you ran it
      </h1>
      <p className="mt-3 max-w-xl text-[14px] leading-relaxed text-muted">
        Your own result beats anything published. Record a step and the answer is worked out again
        by the same rule, with every change shown. Later runs on related molecules will use it too.
      </p>

      {s.revisions.length > 0 && (
        <Section className="mt-9" title="What your notes changed">
          <div className="space-y-2.5">
            {s.revisions.map((r) => {
              const moved = r.before.label !== r.after.label;
              const t = r.outcome === "success" ? TONE.good : TONE.bad;
              return (
                <Card key={r.note_id} className="p-4">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="inline-flex items-center gap-1.5 rounded-chip border px-2 py-0.5 text-[12px] font-medium"
                          style={{ color: t.fg, borderColor: t.border, background: t.bg }}>
                      {r.outcome === "success"
                        ? <CircleCheck size={13} strokeWidth={2} aria-hidden />
                        : <CircleX size={13} strokeWidth={2} aria-hidden />}
                      {r.outcome === "success" ? "It worked" : "It did not work"}
                    </span>
                    <span className="text-[13px] text-muted">
                      {steps.find((x) => x.id === r.step_id)
                        ? `Step ${steps.find((x) => x.id === r.step_id)!.index}`
                        : "A step"}
                    </span>
                    <span className="ml-auto flex items-center gap-2 text-[13px]">
                      <span className="text-muted">{r.before.label} ({Math.round(r.before.confidence * 100)}%)</span>
                      <ArrowRight size={13} className="text-muted" aria-hidden />
                      <span className={moved ? "font-semibold" : "font-medium"}>
                        {r.after.label} ({Math.round(r.after.confidence * 100)}%)
                      </span>
                    </span>
                  </div>
                  <ul className="mt-2.5 space-y-1 text-[13px] leading-relaxed">
                    {r.changes.map((c, i) => (
                      <li key={i} className="flex gap-2"><span className="text-muted">·</span>{c}</li>
                    ))}
                  </ul>
                </Card>
              );
            })}
          </div>
        </Section>
      )}

      <Section className="mt-10" title="Record a result"
               hint={ready ? "Pick the step you ran." : "Available once a run has finished."}>
        <div className="space-y-2">
          {steps.map((step) => {
            const notes = step.detail?.lab_notes ?? [];
            return (
              <Card key={step.id} className="flex flex-wrap items-center gap-3 p-4">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-hairline
                                 text-[12px] font-semibold text-muted">
                  {step.index}
                </span>
                <span className="min-w-0 flex-1 text-[13.5px] font-medium">{stepTitle(s, step)}</span>
                {notes.map((n) => {
                  const t = n.outcome === "success" ? TONE.good : TONE.bad;
                  return (
                    <span key={n.id} className="inline-flex items-center gap-1 rounded-chip border px-2 py-0.5 text-[12px]"
                          style={{ color: t.fg, borderColor: t.border, background: t.bg }}>
                      <FlaskConical size={12} strokeWidth={1.9} aria-hidden />
                      {n.outcome === "success" ? `worked${n.yield_pct ? ` · ${n.yield_pct}%` : ""}` : "did not work"}
                    </span>
                  );
                })}
                <button className="btn-secondary shrink-0" disabled={!ready} onClick={() => setNoting(step)}>
                  I ran this
                </button>
              </Card>
            );
          })}
        </div>
      </Section>

      {noting && <LabNoteDialog step={noting} title={stepTitle(s, noting)} onClose={() => setNoting(null)} />}
    </div>
  );
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="mx-auto max-w-[620px] px-6 py-24 text-center">
      <FlaskConical size={22} strokeWidth={1.5} className="mx-auto text-muted" aria-hidden />
      <div className="mt-3 text-[16px] font-semibold">{title}</div>
      <p className="mt-2 text-[13.5px] leading-relaxed text-muted">{body}</p>
    </div>
  );
}
