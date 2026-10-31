import { ArrowRight, CircleCheck, CircleX, FlaskConical, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useRun } from "../state/runStore";
import type { Revision } from "../state/types";
import { TONE } from "../tokens";
import type { Step } from "./StepCard";

const num = (v: string) => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));
const text = (v: string) => v.trim() || null;

/** "I ran this": a chemist's result on one step. The form starts from the
 *  suggested conditions, so only what was done differently needs typing. */
export function LabNoteDialog({ step, title, onClose }: { step: Step; title: string; onClose: () => void }) {
  const addNote = useRun((s) => s.addNote);
  const c = step.detail?.conditions ?? {};
  const [outcome, setOutcome] = useState<"success" | "failure">("success");
  const [f, setF] = useState({
    reagents: c.reagents?.value ?? "",
    solvent: c.solvent?.value ?? "",
    temperature: c.temperature?.value ? String(parseFloat(c.temperature.value)) : "",
    time: c.time?.value ?? "",
    scale: "",
    yield: "",
    observations: "",
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState<Revision | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      setRevision(await addNote({
        step_id: step.id, outcome,
        yield_pct: num(f.yield), temperature_c: num(f.temperature),
        reagents: f.reagents.split(/[,;]/).map((x) => x.trim()).filter(Boolean),
        solvent: text(f.solvent), time: text(f.time), scale: text(f.scale),
        observations: text(f.observations), notes: text(f.notes),
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // portalled: the page's entrance animation leaves a transform that would trap a fixed overlay
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/30 px-4 py-10"
         onClick={onClose}>
      <div className="w-full max-w-[560px] animate-rise rounded-card border border-hairline bg-surface shadow-lg"
           onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Lab note">
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
          <div>
            <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.08em]"
                 style={{ color: TONE.lab.fg }}>
              <FlaskConical size={13} strokeWidth={2} aria-hidden /> Lab note · step {step.index}
            </div>
            <div className="mt-1 text-[16px] font-semibold leading-snug">{title}</div>
          </div>
          <button onClick={onClose} className="text-muted hover:text-ink" aria-label="Close">
            <X size={18} strokeWidth={1.8} />
          </button>
        </div>

        {revision ? (
          <Result revision={revision} onClose={onClose} />
        ) : (
          <div className="space-y-5 px-5 py-4">
            <Group title="What happened">
              <div className="grid grid-cols-2 gap-2">
                {(["success", "failure"] as const).map((o) => {
                  const on = outcome === o;
                  const t = o === "success" ? TONE.good : TONE.bad;
                  const Icon = o === "success" ? CircleCheck : CircleX;
                  return (
                    <button
                      key={o}
                      onClick={() => setOutcome(o)}
                      className="flex items-center justify-center gap-2 rounded-chip border px-3 py-2.5 text-[13.5px] font-medium"
                      style={on ? { color: t.fg, borderColor: t.border, background: t.bg } : undefined}
                    >
                      <Icon size={16} strokeWidth={1.8} aria-hidden />
                      {o === "success" ? "It worked" : "It did not work"}
                    </button>
                  );
                })}
              </div>
              <Field label="Yield (%)" hint={outcome === "failure" ? "if any product formed" : undefined}>
                <input className="input" inputMode="decimal" value={f.yield} onChange={set("yield")} placeholder="e.g. 64" />
              </Field>
            </Group>

            <Group title="What you used" hint="Filled in from the suggested conditions. Change anything you did differently.">
              <Field label="Reagents"><input className="input" value={f.reagents} onChange={set("reagents")} placeholder="comma separated" /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Solvent"><input className="input" value={f.solvent} onChange={set("solvent")} /></Field>
                <Field label="Temperature (°C)">
                  <input className="input" inputMode="decimal" value={f.temperature} onChange={set("temperature")} />
                </Field>
                <Field label="Time"><input className="input" value={f.time} onChange={set("time")} placeholder="e.g. 4 h" /></Field>
                <Field label="Scale"><input className="input" value={f.scale} onChange={set("scale")} placeholder="e.g. 2 mmol" /></Field>
              </div>
            </Group>

            <Group title="What you saw">
              <textarea className="input min-h-[64px]" value={f.observations} onChange={set("observations")}
                        placeholder="Side products, colour change, precipitate, what TLC or LC-MS showed…" />
            </Group>

            <Group title="Anything else">
              <textarea className="input min-h-[52px]" value={f.notes} onChange={set("notes")} />
            </Group>

            <p className="text-[12.5px] leading-relaxed text-muted">
              Your note becomes evidence from your lab. For this step it outranks any published work, the answer
              is recomputed by the same fixed rule, and you will see exactly what changed. Later runs on
              related molecules will use it too.
            </p>
            {error && <div className="text-[13px]" style={{ color: TONE.bad.fg }}>{error}</div>}
            <div className="flex justify-end gap-2">
              <button className="btn-secondary" onClick={onClose}>Cancel</button>
              <button className="btn-primary" onClick={submit} disabled={busy}>
                {busy ? "Saving…" : "Save note"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  , document.body);
}

function Result({ revision, onClose }: { revision: Revision; onClose: () => void }) {
  const moved = revision.before.label !== revision.after.label;
  return (
    <div className="px-5 py-4">
      <div className="text-[15px] font-semibold">{moved ? "Your note changed the answer" : "Your note was added"}</div>
      <div className="mt-2 flex items-center gap-2 text-[13.5px]">
        <span className="text-muted">{revision.before.label} ({Math.round(revision.before.confidence * 100)}%)</span>
        <ArrowRight size={14} className="text-muted" aria-hidden />
        <span className="font-medium">{revision.after.label} ({Math.round(revision.after.confidence * 100)}%)</span>
      </div>
      <ul className="mt-3 space-y-1.5 text-[13.5px] leading-relaxed">
        {revision.changes.map((c, i) => <li key={i} className="flex gap-2"><span className="text-muted">·</span>{c}</li>)}
      </ul>
      <p className="mt-4 text-[12.5px] leading-relaxed text-muted">
        To have the Builder and Skeptic argue over your result, run the molecule again: the new run starts
        with your note in its evidence.
      </p>
      <div className="mt-4 flex justify-end">
        <button className="btn-primary" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-2.5">
      <legend className="text-[13.5px] font-semibold">{title}</legend>
      {hint && <p className="-mt-1 text-[12.5px] text-muted">{hint}</p>}
      {children}
    </fieldset>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-[12.5px]">
      <span className="text-muted">{label}{hint && <span className="text-muted/70"> · {hint}</span>}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
