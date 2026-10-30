import {
  CircleCheck, CircleDashed, CircleMinus, CircleX, TriangleAlert, type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { GRADE, TONE, type Grade } from "../tokens";

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
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-chip border px-2.5 py-1 text-[12.5px]
        font-medium ${dashed ? "border-dashed" : ""} ${onClick ? "cursor-pointer hover:brightness-95" : ""}`}
    >
      {children}
    </span>
  );
}

/** One icon per status, shared by every view, so a mark means the same
 *  thing everywhere. */
export const STATUS_ICON: Record<string, LucideIcon> = {
  pass: CircleCheck,
  warn: TriangleAlert,
  fail: CircleX,
  skip: CircleMinus,
  pending: CircleDashed,
  running: CircleDashed,
};

export const GRADE_ICON: Record<string, LucideIcon> = {
  direct: CircleCheck,
  analog: CircleCheck,
  weak: TriangleAlert,
  none: CircleMinus,
  blocked: CircleX,
};

export function StatusIcon({ status, size = 16 }: { status: string; size?: number }) {
  const Icon = STATUS_ICON[status] ?? CircleMinus;
  const tone = TONE[status === "pass" ? "good" : status === "warn" ? "warn" : status === "fail" ? "bad" : "neutral"];
  return <Icon size={size} strokeWidth={1.8} style={{ color: tone.fg }} className="shrink-0" aria-hidden />;
}

/** Evidence strength for one step: always icon + word, never colour alone. */
export function GradeBadge({ grade, sources, onClick }: { grade: string; sources?: number; onClick?: () => void }) {
  const g = GRADE[(grade as Grade)] ?? GRADE.none;
  const Icon = GRADE_ICON[grade] ?? CircleMinus;
  return (
    <Pill tone={g.tone as keyof typeof TONE} title={g.plain} onClick={onClick}>
      <Icon size={14} strokeWidth={2} aria-hidden />
      {g.label}
      {sources !== undefined && sources > 0 && (
        <span className="font-normal opacity-75">· {sources} source{sources === 1 ? "" : "s"}</span>
      )}
    </Pill>
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

export function Empty({ icon: Icon, title, hint }: { icon?: LucideIcon; title: string; hint?: string }) {
  return (
    <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 px-6 text-center">
      {Icon && <Icon size={22} strokeWidth={1.5} className="mb-1 text-muted/70" aria-hidden />}
      <div className="text-[14px]">{title}</div>
      {hint && <div className="max-w-md text-[13px] leading-relaxed text-muted">{hint}</div>}
    </div>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`mono text-muted ${className}`}>{children}</span>;
}

/** A short version first, the rest on request: long agent text is the
 *  main source of "dumped data", so nothing long is shown in full by default. */
export function MoreText({ short, full }: { short: string; full: string }) {
  const [open, setOpen] = useState(false);
  if (short === full) return <>{full}</>;
  return (
    <>
      {open ? full : short}{" "}
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        className="text-[12.5px] text-muted underline decoration-hairline underline-offset-4 hover:text-ink"
      >
        {open ? "less" : "more"}
      </button>
    </>
  );
}

/** Section heading used by every view: a question the section answers. */
export function Section({
  title, hint, children, className = "", action,
}: { title: string; hint?: string; children: ReactNode; className?: string; action?: ReactNode }) {
  return (
    <section className={className}>
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <h2 className="text-[17px] font-semibold tracking-[-0.01em]">{title}</h2>
          {hint && <p className="mt-0.5 text-[13px] text-muted">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
