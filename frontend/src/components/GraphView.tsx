import { ArrowRight, Maximize2, Minus, PackageCheck, Plus, Target, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { routeSteps, sourceCount, targetName, useRun } from "../state/runStore";
import type { Reaction } from "../state/types";
import { plural } from "../textutil";
import { C, GRADE, reactionPlain, type Grade } from "../tokens";
import { GradeBadge, Mono } from "./primitives";
import { Structure } from "./Structure";

type S = ReturnType<typeof useRun.getState>;

/** The graph tells how the target is reached: a tidy tree read left to right,
 *  from chemicals you can buy, through each reaction and what it makes, to the
 *  target. Paths that were explored and not chosen are hidden unless asked for. */

const MOL_W = 150;
const MOL_H = 156;
const RX_W = 212;
const RX_H = 104;
const GAP = 36;                     // horizontal gap between a box and the next column
const ROW = MOL_H + 22;              // vertical slot per leaf
const LEVEL = MOL_W + RX_W + GAP * 2;
const MAX_DEPTH = 6;
const MAX_ALTERNATIVES = 3;          // alternative reactions shown per molecule

interface Box { key: string; id: string; kind: "mol" | "rx"; x: number; y: number; depth: number }
interface Edge { from: Box; to: Box; route: boolean; blocked: boolean }

function layout(s: S, showAll: boolean) {
  const steps = routeSteps(s);
  const routeIds = new Set(steps.map((x) => x.id));
  const haveRoute = routeIds.size > 0;
  const hyps = Object.values(s.reactions).filter((r) => r.kind === "hypothesis");
  const target = s.targetInfo?.inchikey ?? null;

  const makers = (mol: string): Reaction[] => {
    const all = hyps.filter((r) => r.products[0] === mol);
    const chosen = all.filter((r) => routeIds.has(r.id));
    if (haveRoute && !showAll) return chosen;
    const rest = all
      .filter((r) => !routeIds.has(r.id) && (showAll || r.critic !== "block"))
      .sort((a, b) => Number(a.critic === "block") - Number(b.critic === "block"));
    return [...chosen, ...rest].slice(0, Math.max(chosen.length, MAX_ALTERNATIVES));
  };

  // tidy tree: leaves take the next free row; a parent sits centred on its children
  const boxes: Box[] = [];
  const edges: Edge[] = [];
  let leaf = 0;
  let deepest = 0;

  const place = (mol: string, depth: number, path: string, seen: Set<string>): Box => {
    deepest = Math.max(deepest, depth);
    const rxs = depth < MAX_DEPTH && !seen.has(mol) ? makers(mol) : [];
    const box: Box = { key: `${path}/${mol}`, id: mol, kind: "mol", x: 0, y: 0, depth };
    if (!rxs.length) {
      box.y = leaf++ * ROW;
      boxes.push(box);
      return box;
    }
    const next = new Set(seen).add(mol);
    const rxBoxes = rxs.map((rx) => {
      const rb: Box = { key: `${path}/${mol}/${rx.id}`, id: rx.id, kind: "rx", x: 0, y: 0, depth };
      const kids = rx.reactants.map((r) => place(r, depth + 1, rb.key, next));
      rb.y = kids.reduce((a, k) => a + k.y, 0) / Math.max(kids.length, 1);
      const route = routeIds.has(rx.id);
      const blocked = rx.critic === "block";
      for (const k of kids) edges.push({ from: k, to: rb, route, blocked });
      edges.push({ from: rb, to: box, route, blocked });
      boxes.push(rb);
      return rb;
    });
    box.y = rxBoxes[0].y;
    boxes.push(box);
    return box;
  };

  if (target && s.molecules[target]) place(target, 0, "", new Set());

  // left to right: the deepest starting materials on the left, the target on the right
  for (const b of boxes) {
    const col = deepest - b.depth;
    b.x = b.kind === "mol" ? col * LEVEL : (col - 1) * LEVEL + MOL_W + GAP;
  }
  const width = deepest * LEVEL + MOL_W;
  const height = Math.max(leaf, 1) * ROW;
  return { boxes, edges, width, height, steps, routeIds };
}

function MolBox({ s, b, stepOf, selected }: { s: S; b: Box; stepOf: Map<string, number>; selected: boolean }) {
  const m = s.molecules[b.id];
  if (!m) return null;
  const isTarget = b.id === s.targetInfo?.inchikey;
  const made = stepOf.get(b.id);
  const tag = isTarget ? "target" : m.purchasable ? "buy" : made ? `made in step ${made}` : "intermediate";
  return (
    <button
      onClick={() => s.select({ molecule: b.id, step: null })}
      className={`absolute flex flex-col items-center rounded-card border bg-surface px-2 pb-2 pt-1 text-center
                  transition-shadow hover:shadow-[0_1px_6px_rgba(28,27,25,.08)]
                  ${selected ? "border-accent/60 ring-1 ring-accent/30" : "border-hairline"}`}
      style={{
        left: b.x, top: b.y, width: MOL_W, height: MOL_H,
        borderColor: isTarget && !selected ? C.accent : undefined,
      }}
    >
      <Structure smiles={m.smiles} width={MOL_W - 16} height={84} framed={false} />
      <span className="mt-0.5 line-clamp-2 break-words text-[12px] font-medium leading-tight" title={m.name}>{m.name}</span>
      <span className="mt-auto flex items-center gap-1 text-[11px]" style={{ color: isTarget ? C.accent : C.muted }}>
        {isTarget ? <Target size={11} strokeWidth={2} aria-hidden /> : m.purchasable ? <PackageCheck size={11} strokeWidth={2} aria-hidden /> : null}
        {tag}
      </span>
    </button>
  );
}

function RxBox({ s, b, step, selected }: { s: S; b: Box; step: number | null; selected: boolean }) {
  const rx = s.reactions[b.id];
  if (!rx) return null;
  const blocked = rx.critic === "block";
  const grade = blocked ? "blocked" : (s.verdict?.steps.find((x) => x.hypothesis_id === rx.id)?.grade ?? null);
  const n = sourceCount(s, rx.id);
  const dim = !step;
  return (
    <button
      onClick={() => s.select({ step: rx.id, molecule: null })}
      className={`absolute flex flex-col justify-center rounded-card border px-3 py-2 text-left transition-shadow
                  hover:shadow-[0_1px_6px_rgba(28,27,25,.08)]
                  ${selected ? "border-accent/60 ring-1 ring-accent/30" : dim ? "border-dashed border-hairline" : "border-hairline"}
                  ${dim ? "bg-ground" : "bg-surface"}`}
      style={{ left: b.x, top: b.y + (MOL_H - RX_H) / 2, width: RX_W, height: RX_H, opacity: dim ? 0.8 : 1 }}
    >
      <span className="label">{step ? `Step ${step}` : blocked ? "Ruled out" : "Not chosen"}</span>
      <span className="mt-0.5 truncate text-[13px] font-medium leading-snug" title={rx.classes[0]}>{rx.classes[0] ?? "Chemical step"}</span>
      <span className="line-clamp-1 text-[11.5px] leading-snug text-muted" title={reactionPlain(rx.classes[0])}>{reactionPlain(rx.classes[0])}</span>
      <span className="mt-1.5">
        {grade ? (
          <GradeBadge grade={grade} sources={n} />
        ) : (
          <span className="text-[11.5px] text-muted">{n ? `${plural(n, "source")} found` : "looking for evidence…"}</span>
        )}
      </span>
    </button>
  );
}

function curve(e: Edge) {
  const fromW = e.from.kind === "mol" ? MOL_W : RX_W;
  const x1 = e.from.x + fromW;
  const y1 = e.from.y + MOL_H / 2;
  const x2 = e.to.x;
  const y2 = e.to.y + MOL_H / 2;
  const mid = (x1 + x2) / 2;
  return `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
}

function Inspector({ s }: { s: S }) {
  const mol = s.selectedMolecule ? s.molecules[s.selectedMolecule] : null;
  const rx = !mol && s.selectedStep ? s.reactions[s.selectedStep] : null;
  if (mol) {
    const isTarget = mol.id === s.targetInfo?.inchikey;
    return (
      <>
        <div className="label">{isTarget ? "Target" : mol.purchasable ? "Starting material" : "Intermediate"}</div>
        <h2 className="mt-1 text-[19px] font-semibold leading-tight tracking-[-0.015em]">{mol.name}</h2>
        <Structure smiles={mol.smiles} width={268} height={200} className="mt-4" />
        <p className="mt-3 text-[13px] leading-relaxed text-muted">
          {isTarget
            ? "The molecule you asked about."
            : mol.purchasable
              ? mol.purchasable_basis === "catalog"
                ? "Sold as a standard building block, so the route can start here."
                : mol.purchasable_basis === "vendors"
                  ? "Listed by several chemical suppliers, so the route can start here."
                  : "A small, common molecule, assumed to be available."
              : "Not bought: it has to be made by an earlier step."}
        </p>
        <Mono className="mt-3 block break-all text-[11.5px]">{mol.smiles}</Mono>
      </>
    );
  }
  if (rx) {
    const sv = s.verdict?.steps.find((x) => x.hypothesis_id === rx.id);
    const g = GRADE[(rx.critic === "block" ? "blocked" : sv?.grade ?? "none") as Grade];
    const onRoute = !!sv;
    const name = (id: string) => s.molecules[id]?.name ?? id;
    return (
      <>
        <div className="label">{onRoute ? "Step on the route" : rx.critic === "block" ? "Ruled out" : "Explored, not chosen"}</div>
        <h2 className="mt-1 text-[19px] font-semibold leading-tight tracking-[-0.015em]">{rx.classes[0] ?? "Chemical step"}</h2>
        <p className="mt-1 text-[13px] text-muted">{reactionPlain(rx.classes[0])}.</p>
        <p className="mt-4 text-[13px] leading-relaxed">
          {rx.reactants.map(name).join(" + ")} <span className="text-muted">→</span>{" "}
          <span className="font-medium">{name(rx.products[0])}</span>
        </p>
        {onRoute && <p className="mt-4 text-[13px] leading-relaxed">{g.plain}</p>}
        {onRoute && (
          <button
            className="mt-4 inline-flex items-center gap-1 text-[13px] text-accent hover:underline"
            onClick={() => { s.select({ step: rx.id, node: null }); s.setTab("verification"); }}
          >
            Why we trust this step <ArrowRight size={13} strokeWidth={2} aria-hidden />
          </button>
        )}
      </>
    );
  }
  return (
    <div className="text-[13px] leading-relaxed text-muted">
      Click a molecule or a step to see what it is and why it is there.
    </div>
  );
}

export function GraphView() {
  const s = useRun();
  const [showAll, setShowAll] = useState(false);
  const [zoom, setZoom] = useState<number | null>(null);   // null = fit to width
  const hostRef = useRef<HTMLDivElement>(null);
  const [hostW, setHostW] = useState(900);
  const [hostH, setHostH] = useState(600);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => { setHostW(el.clientWidth); setHostH(el.clientHeight); });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { boxes, edges, width, height, steps, routeIds } = useMemo(
    () => layout(s, showAll),
    [s.reactions, s.molecules, s.verdict, s.targetInfo, showAll],   // eslint-disable-line react-hooks/exhaustive-deps
  );
  const stepOf = useMemo(() => new Map(steps.map((x) => [x.product ?? "", x.index])), [steps]);
  const stepNo = useMemo(() => new Map(steps.map((x) => [x.id, x.index])), [steps]);

  const pad = 40;
  const fit = Math.min(1, (hostW - pad * 2) / Math.max(width, 1));
  const scale = zoom ?? fit;

  const buy = new Set(steps.flatMap((x) => x.reactants).filter((m) => s.molecules[m]?.purchasable)).size;
  const explored = Object.values(s.reactions).filter((r) => r.kind === "hypothesis").length;
  const backed = steps.filter((x) => {
    const g = s.verdict?.steps.find((v) => v.hypothesis_id === x.id)?.grade;
    return g === "direct" || g === "analog";
  }).length;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* the story in one line */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-hairline px-6 py-3.5 text-[13.5px]">
          {routeIds.size ? (
            <>
              <span className="flex items-center gap-1.5"><PackageCheck size={15} strokeWidth={1.8} aria-hidden /> Buy {plural(buy, "chemical")}</span>
              <ArrowRight size={14} className="text-muted" aria-hidden />
              <span>{plural(steps.length, "reaction")}, {backed === steps.length ? "each backed by published work" : `${backed} backed by published work`}</span>
              <ArrowRight size={14} className="text-muted" aria-hidden />
              <span className="flex items-center gap-1.5 font-medium" style={{ color: C.accent }}>
                <Target size={15} strokeWidth={1.8} aria-hidden /> {targetName(s)}
              </span>
            </>
          ) : (
            <span className="text-muted">
              {explored
                ? `Working backwards from ${targetName(s)}: ${plural(explored, "possible step")} so far.`
                : "The route appears here as possible steps are found."}
            </span>
          )}
          <div className="ml-auto flex items-center gap-3">
            {routeIds.size > 0 && explored > steps.length && (
              <label className="flex cursor-pointer select-none items-center gap-2 text-[12.5px] text-muted">
                <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} className="accent-accent" />
                Show {plural(explored - steps.length, "other path")} explored
              </label>
            )}
            <div className="flex items-center rounded-chip border border-hairline bg-surface">
              <button className="p-1.5 text-muted hover:text-ink" title="Zoom out" onClick={() => setZoom(Math.max(0.3, scale - 0.15))}>
                <Minus size={14} aria-hidden />
              </button>
              <button className="p-1.5 text-muted hover:text-ink" title="Fit" onClick={() => setZoom(null)}>
                <Maximize2 size={13} aria-hidden />
              </button>
              <button className="p-1.5 text-muted hover:text-ink" title="Zoom in" onClick={() => setZoom(Math.min(1.5, scale + 0.15))}>
                <Plus size={14} aria-hidden />
              </button>
            </div>
          </div>
        </div>

        <div ref={hostRef} className="relative min-h-0 flex-1 overflow-auto pb-24">
          {boxes.length ? (
            <div
              className="mx-auto"
              style={{
                width: width * scale + pad * 2, height: height * scale + pad * 2,
                marginTop: Math.max(0, (hostH - height * scale - pad * 2) / 2 - 40),
              }}
            >
              <div
                className="relative"
                style={{ width, height, transform: `translate(${pad}px, ${pad}px) scale(${scale})`, transformOrigin: "0 0" }}
              >
                <svg width={width} height={height} className="absolute inset-0 overflow-visible" aria-hidden>
                  {edges.map((e, i) => (
                    <path
                      key={i}
                      d={curve(e)}
                      fill="none"
                      stroke={e.blocked ? C.rejected : e.route ? C.accent : "#C9C3B6"}
                      strokeWidth={e.route ? 1.8 : 1.2}
                      strokeDasharray={e.route ? undefined : "4 4"}
                      strokeOpacity={e.route ? 0.75 : 0.9}
                    />
                  ))}
                </svg>
                {boxes.map((b) =>
                  b.kind === "mol" ? (
                    <MolBox key={b.key} s={s} b={b} stepOf={stepOf} selected={s.selectedMolecule === b.id} />
                  ) : (
                    <RxBox key={b.key} s={s} b={b} step={stepNo.get(b.id) ?? null} selected={s.selectedStep === b.id && !s.selectedMolecule} />
                  ),
                )}
              </div>
            </div>
          ) : (
            <div className="grid h-full place-items-center text-[13px] text-muted">
              The route appears here as possible steps are found.
            </div>
          )}
        </div>
      </div>

      {/* the inspector only takes space once there is something to inspect */}
      {(s.selectedMolecule || s.selectedStep) && (
        <aside className="relative w-[310px] shrink-0 animate-rise overflow-y-auto border-l border-hairline bg-ground px-5 py-6 pb-28">
          <button
            className="absolute right-3 top-3 rounded-chip p-1 text-muted hover:bg-hairline/50 hover:text-ink"
            title="Close"
            onClick={() => s.select({ molecule: null, step: null })}
          >
            <X size={15} strokeWidth={1.8} aria-hidden />
          </button>
          <Inspector s={s} />
        </aside>
      )}
    </div>
  );
}
