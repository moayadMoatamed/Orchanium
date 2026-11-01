import { Network, ScrollText } from "lucide-react";
import { useState } from "react";
import { GraphView } from "./GraphView";
import { ResultView } from "./ResultView";

/** The answer, and the same answer as a map. One tab, because a chemist asks
 *  one question here: what is the route and can I trust it? */
export function RouteTab({ onRetry }: { onRetry: (target: string) => void }) {
  const [pane, setPane] = useState<"answer" | "map">("answer");
  const panes = [
    { id: "answer" as const, label: "The answer", icon: ScrollText },
    { id: "map" as const, label: "Route map", icon: Network },
  ];
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
      </div>
      <div className="min-h-0 flex-1">
        {pane === "answer"
          ? <div className="h-full overflow-y-auto pb-28"><ResultView onRetry={onRetry} /></div>
          : <GraphView />}
      </div>
    </div>
  );
}
