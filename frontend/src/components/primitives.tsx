import type { ReactNode } from "react";
import { GRADE, STATUS_TONE, TONE, type Grade } from "../tokens";

export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`label ${className}`}>{children}</div>;
}

export function Pill({
  tone = "neutral", children, title, onClick, dashed = false,
}: {
  tone?: keyof typeof TONE; children: ReactNode; title?: string;
  onClick?: () => void; dashed?: boolean;
}) {
  const t = TONE[tone];
  return (
    <span
      title={title}
      onClick={onClick}
      style={{ color: t.fg, background: t.bg, borderColor: t.border }}
      className={`inline-flex items-center gap-1.5 rounded-chip border px-2.5 py-1 text-[12.5px]
        font-medium ${dashed ? "border-dashed" : ""} ${onClick ? "cursor-pointer hover:brightness-95" : ""}`}
    >
      {children}
    </span>
  );
}

const GRADE_ICON: Record<string, string> = {
  direct: "✓", analog: "✓", weak: "!", none: "–", blocked: "×",
};

/** Evidence strength for one step: always icon + word, never colour alone. */
export function GradeBadge({ grade, sources, onClick }: { grade: string; sources?: number; onClick?: () => void }) {
  const g = GRADE[(grade as Grade)] ?? GRADE.none;
  return (
    <Pill tone={g.tone as keyof typeof TONE} title={g.blurb} onClick={onClick}>
      <span aria-hidden>{GRADE_ICON[grade] ?? "–"}</span>
      {g.label}
      {sources !== undefined && sources > 0 && (
        <span className="opacity-70">· {sources} source{sources === 1 ? "" : "s"}</span>
      )}
    </Pill>
  );
}

export function StatusDot({ status, live = false }: { status: string; live?: boolean }) {
  const tone = TONE[STATUS_TONE[status] ?? "neutral"];
  return (
    <span
      className={`inline-block h-[7px] w-[7px] rounded-full ${live ? "animate-livedot" : ""}`}
      style={{ background: tone.fg }}
    />
  );
}

export function Card({
  children, className = "", onClick, active = false, tone,
}: {
  children: ReactNode; className?: string; onClick?: () => void;
  active?: boolean; tone?: keyof typeof TONE;
}) {
  const t = tone ? TONE[tone] : null;
  return (
    <div
      onClick={onClick}
      style={t ? { borderColor: t.border, background: t.bg } : undefined}
      className={`card ${onClick ? "cursor-pointer transition-colors hover:border-ink/25" : ""}
        ${active ? "ring-1 ring-accent/40 border-accent/40" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-1.5 text-center">
      <div className="text-[14px] text-muted">{title}</div>
      {hint && <div className="max-w-sm text-[12.5px] text-muted/75">{hint}</div>}
    </div>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`mono text-muted ${className}`}>{children}</span>;
}
