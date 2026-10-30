import {
  forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY,
  type SimulationLinkDatum, type SimulationNodeDatum,
} from "d3-force";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRun } from "../state/runStore";
import { C, SHAPE_LEGEND, type NodeShape } from "../tokens";
import { Label, Mono } from "./primitives";
import { Structure } from "./Structure";

interface N extends SimulationNodeDatum {
  id: string;
  label: string;
  shape: NodeShape;
  kind: "molecule" | "reaction";
  onRoute: boolean;
}
interface L extends SimulationLinkDatum<N> {
  onRoute: boolean;
  rejected: boolean;
}

/** Shape carries the meaning; colour only marks the target and the chosen route. */
function NodeGlyph({ n }: { n: N }) {
  const fill = n.shape === "target" ? C.accent : n.shape === "rejected" ? C.rejected : C.ink;
  switch (n.shape) {
    case "purchasable":
      return <rect x={-4.5} y={-4.5} width={9} height={9} fill={fill} />;
    case "proposed":
      return <circle r={5} fill={C.ground} stroke={C.ink} strokeWidth={1.4} />;
    case "reaction":
      return <rect x={-3.2} y={-3.2} width={6.4} height={6.4} fill="#9b958a" transform="rotate(45)" />;
    case "rejected":
      return <circle r={4.5} fill={C.rejected} />;
    case "target":
      return (
        <>
          <circle r={11} fill={C.accent} opacity={0.12} />
          <circle r={6.5} fill={C.accent} />
        </>
      );
    default:
      return <circle r={5} fill={fill} />;
  }
}

export function GraphView() {
  const s = useRun();
  const hostRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 900, h: 620 });
  const [, setFrame] = useState(0);
  const simRef = useRef<ReturnType<typeof forceSimulation<N, L>> | null>(null);
  const nodesRef = useRef<Map<string, N>>(new Map());
  const linksRef = useRef<L[]>([]);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const routeIds = useMemo(() => new Set(s.verdict?.route ?? []), [s.verdict]);
  const onRouteMolecules = useMemo(() => {
    const set = new Set<string>();
    for (const id of routeIds) {
      const rx = s.reactions[id];
      if (!rx) continue;
      rx.reactants.forEach((m) => set.add(m));
      set.add(rx.products[0]);
    }
    return set;
  }, [routeIds, s.reactions]);

  /** Rebuild the node/link sets from the graph, keeping existing positions so
   *  the layout grows rather than jumping when new nodes arrive. */
  const { nodes, links } = useMemo(() => {
    const keep = nodesRef.current;
    const next = new Map<string, N>();
    const ls: L[] = [];

    const hypotheses = Object.values(s.reactions).filter((r) => r.kind === "hypothesis");
    const shown = s.showRuledOut ? hypotheses : hypotheses.filter((r) => r.critic !== "block" || routeIds.has(r.id));

    const addMol = (id: string) => {
      if (next.has(id)) return next.get(id)!;
      const m = s.molecules[id];
      if (!m) return null;
      const shape: NodeShape =
        m.id === s.targetInfo?.inchikey ? "target" : m.purchasable ? "purchasable"
          : m.roles?.includes("clue") ? "literature" : "proposed";
      const prev = keep.get(id);
      const n: N = {
        id, label: m.name, shape, kind: "molecule",
        onRoute: onRouteMolecules.has(id),
        x: prev?.x, y: prev?.y, vx: prev?.vx, vy: prev?.vy,
      };
      next.set(id, n);
      return n;
    };

    for (const rx of shown) {
      const prev = keep.get(rx.id);
      const rejected = rx.critic === "block";
      const rn: N = {
        id: rx.id, label: rx.classes[0] ?? "reaction",
        shape: rejected ? "rejected" : "reaction", kind: "reaction",
        onRoute: routeIds.has(rx.id),
        x: prev?.x, y: prev?.y, vx: prev?.vx, vy: prev?.vy,
      };
      next.set(rx.id, rn);
      for (const r of rx.reactants) {
        if (addMol(r)) ls.push({ source: r, target: rx.id, onRoute: rn.onRoute, rejected });
      }
      if (addMol(rx.products[0])) {
        ls.push({ source: rx.id, target: rx.products[0], onRoute: rn.onRoute, rejected });
      }
    }
    nodesRef.current = next;
    linksRef.current = ls;
    return { nodes: [...next.values()], links: ls };
  }, [s.reactions, s.molecules, s.showRuledOut, routeIds, onRouteMolecules, s.targetInfo]);

  useEffect(() => {
    if (!nodes.length) return;
    const sim = forceSimulation<N, L>(nodes)
      .force("charge", forceManyBody<N>().strength((d) => (d.kind === "reaction" ? -140 : -260)))
      .force(
        "link",
        forceLink<N, L>(links).id((d) => d.id).distance((l) => (l.onRoute ? 62 : 86)).strength(0.75),
      )
      .force("collide", forceCollide<N>().radius((d) => (d.kind === "reaction" ? 16 : 30)))
      .force("x", forceX(size.w / 2).strength(0.045))
      .force("y", forceY<N>((d) => (d.shape === "target" ? size.h * 0.56 : size.h / 2)).strength(0.06))
      .alpha(0.8)
      .alphaDecay(0.035)
      .on("tick", () => setFrame((f) => f + 1));
    simRef.current = sim;
    return () => {
      sim.stop();
    };
  }, [nodes, links, size.w, size.h]);

  const sel = s.selectedMolecule ? s.molecules[s.selectedMolecule] : null;
  const selSources = useMemo(() => {
    if (!sel) return [];
    const out: { title: string; url: string | null; kind: string }[] = [];
    for (const rx of Object.values(s.reactions)) {
      if (rx.kind !== "observed" || ![...rx.reactants, ...rx.products].includes(sel.id)) continue;
      for (const cid of rx.clue_ids) {
        const node = s.prov[`clue:${cid}`];
        const src = node?.details?.source;
        if (src) out.push({ title: src.title, url: src.url, kind: src.kind });
      }
    }
    return out.slice(0, 6);
  }, [sel, s.reactions, s.prov]);

  return (
    <div className="flex h-full min-h-0">
      <div ref={hostRef} className="relative min-w-0 flex-1">
        <svg width={size.w} height={size.h} className="block">
          <g>
            {links.map((l, i) => {
              const a = l.source as N;
              const b = l.target as N;
              if (a.x == null || b.x == null) return null;
              return (
                <line
                  key={i}
                  x1={a.x} y1={a.y!} x2={b.x} y2={b.y!}
                  stroke={l.rejected ? C.rejected : l.onRoute ? C.accent : "#CFC9BC"}
                  strokeWidth={l.onRoute ? 1.5 : 1}
                  strokeOpacity={l.rejected ? 0.55 : l.onRoute ? 0.9 : 0.75}
                />
              );
            })}
          </g>
          <g>
            {nodes.map((n) => {
              if (n.x == null) return null;
              const isSel = s.selectedMolecule === n.id || s.selectedStep === n.id;
              return (
                <g
                  key={n.id}
                  transform={`translate(${n.x},${n.y})`}
                  className="cursor-pointer"
                  onClick={() =>
                    n.kind === "molecule"
                      ? s.select({ molecule: n.id, step: null })
                      : s.select({ step: n.id, molecule: null })
                  }
                >
                  {isSel && <circle r={14} fill="none" stroke={C.accent} strokeWidth={1.2} opacity={0.5} />}
                  <NodeGlyph n={n} />
                  {n.kind === "molecule" && (
                    <text
                      x={11} y={4}
                      fontSize={11.5}
                      fill={n.shape === "target" ? C.ink : C.muted}
                      fontWeight={n.shape === "target" ? 600 : 400}
                      className="pointer-events-none select-none"
                    >
                      {n.label.length > 34 ? `${n.label.slice(0, 33)}…` : n.label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        {!nodes.length && (
          <div className="absolute inset-0 grid place-items-center text-[13px] text-muted">
            The graph appears as candidate steps and evidence arrive.
          </div>
        )}

        <div className="absolute bottom-[72px] left-1/2 flex -translate-x-1/2 flex-wrap items-center
                        justify-center gap-x-4 gap-y-1 rounded-chip border border-hairline bg-hairline/55
                        px-4 py-2 backdrop-blur">
          {SHAPE_LEGEND.map(({ shape, label }) => (
            <span key={shape} className="flex items-center gap-1.5 text-[12px] text-muted">
              <svg width="14" height="14" viewBox="-7 -7 14 14">
                <NodeGlyph n={{ shape, kind: "molecule" } as N} />
              </svg>
              {label}
            </span>
          ))}
          <button
            onClick={s.toggleRuledOut}
            className="ml-1 text-[12px] text-muted underline decoration-hairline underline-offset-4 hover:text-ink"
          >
            {s.showRuledOut ? "hide ruled out" : "show ruled out"}
          </button>
        </div>
      </div>

      <aside className="hidden w-[310px] shrink-0 overflow-y-auto border-l border-hairline px-5 py-6 xl:block">
        {sel ? (
          <>
            <h2 className="text-[20px] font-semibold leading-tight tracking-[-0.015em]">{sel.name}</h2>
            <div className="mt-1 text-[13px] text-muted">
              {sel.id === s.targetInfo?.inchikey
                ? "Target molecule"
                : sel.purchasable
                  ? "Buyable starting material"
                  : sel.roles?.includes("clue")
                    ? "Appears in published work"
                    : "Proposed intermediate"}
            </div>
            <Structure smiles={sel.smiles} width={268} height={200} className="mt-4" />
            <Mono className="mt-3 block break-all">{sel.smiles}</Mono>
            {sel.purchasable && (
              <div className="mt-2 text-[12.5px] text-muted">{sel.purchasable_basis === "catalog"
                ? "In the curated building-block list."
                : sel.purchasable_basis === "vendors"
                  ? "Listed by chemical suppliers."
                  : "Small, simple molecule (heuristic)."}</div>
            )}
            {selSources.length > 0 && (
              <>
                <Label className="mb-2 mt-6">Sources</Label>
                {selSources.map((src, i) => (
                  <a
                    key={i}
                    href={src.url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="block border-b border-hairline py-2.5 text-[13px] last:border-0 hover:text-accent"
                  >
                    <span className="text-muted">[{src.kind}]</span> {src.title}
                  </a>
                ))}
              </>
            )}
          </>
        ) : (
          <div className="text-[13px] text-muted">
            Click any node to inspect its structure and the sources it appears in.
          </div>
        )}
      </aside>
    </div>
  );
}
