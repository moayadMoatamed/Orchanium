import { MessagesSquare, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { DebateView } from "./DebateView";
import { VerificationView } from "./VerificationView";

/** Why the answer is what it is: the argument the two agents had, and the
 *  checks run on the evidence underneath it. Both answer the same question,
 *  so they live together rather than as two tabs a chemist has to reconcile. */
export function ReasoningView() {
  const [pane, setPane] = useState<"argument" | "checks">("argument");
  const panes = [
    { id: "argument" as const, label: "The argument", icon: MessagesSquare,
      hint: "What the two agents said, and which objections still stand" },
    { id: "checks" as const, label: "The checks", icon: ShieldCheck,
      hint: "Where each number came from, source by source" },
  ];
  const current = panes.find((p) => p.id === pane)!;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-hairline px-6 py-2.5">
        <div className="flex items-center gap-1 rounded-chip border border-hairline bg-surface p-0.5">
          {panes.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setPane(id)}
              aria-pressed={pane === id}
              className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-chip px-3 py-1.5 text-[13px]
                          font-medium transition-colors ${pane === id ? "bg-ink text-white" : "text-muted hover:text-ink"}`}
            >
              <Icon size={14} strokeWidth={1.9} aria-hidden />
              {label}
            </button>
          ))}
        </div>
        <span className="hidden text-[12.5px] text-muted md:inline">{current.hint}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {pane === "argument" ? <DebateView /> : <VerificationView />}
      </div>
    </div>
  );
}
