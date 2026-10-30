/** The whole UI is a pure reduction of the event stream, so a live run and a
 *  replayed one render identically. Nothing here talks to the network except
 *  `connect`, which attaches an EventSource. */
import { create } from "zustand";
import type {
  AgentState, Cost, Molecule, ProvNode, Reaction, ReportData, RouteVerdict, TargetInfo,
} from "./types";

export type Tab = "result" | "graph" | "verification" | "debate";

interface RunState {
  runId: string | null;
  status: "idle" | "running" | "done" | "failed";
  target: string;
  targetInfo: TargetInfo | null;
  blind: boolean;
  startedAt: number | null;
  finishedAt: number | null;
  lastEventTs: number | null;

  molecules: Record<string, Molecule>;
  reactions: Record<string, Reaction>;
  prov: Record<string, ProvNode>;
  provOrder: string[];
  agents: Record<string, AgentState>;
  agentOrder: string[];
  cost: Cost;
  verdict: RouteVerdict | null;
  report: { markdown: string; data: ReportData } | null;
  summary: Record<string, any> | null;

  tab: Tab;
  selectedStep: string | null;
  selectedNode: string | null;
  selectedMolecule: string | null;
  showRuledOut: boolean;

  setTab: (t: Tab) => void;
  select: (p: { step?: string | null; node?: string | null; molecule?: string | null }) => void;
  toggleRuledOut: () => void;
  reset: (runId: string, target: string) => void;
  apply: (kind: string, data: any, ts?: number) => void;
  connect: (runId: string, replaySpeed?: number) => () => void;
}

const EMPTY_COST: Cost = {
  llm_calls: 0, tokens_in: 0, tokens_out: 0, searches: 0, sam_images: 0, usd: 0,
};

export const useRun = create<RunState>((set, get) => ({
  runId: null,
  status: "idle",
  target: "",
  targetInfo: null,
  blind: false,
  startedAt: null,
  finishedAt: null,
  lastEventTs: null,
  molecules: {},
  reactions: {},
  prov: {},
  provOrder: [],
  agents: {},
  agentOrder: [],
  cost: EMPTY_COST,
  verdict: null,
  report: null,
  summary: null,
  tab: "result",
  selectedStep: null,
  selectedNode: null,
  selectedMolecule: null,
  showRuledOut: false,

  setTab: (tab) => set({ tab }),
  select: ({ step, node, molecule }) =>
    set((s) => ({
      selectedStep: step !== undefined ? step : s.selectedStep,
      selectedNode: node !== undefined ? node : s.selectedNode,
      selectedMolecule: molecule !== undefined ? molecule : s.selectedMolecule,
    })),
  toggleRuledOut: () => set((s) => ({ showRuledOut: !s.showRuledOut })),

  reset: (runId, target) =>
    set({
      runId, target, status: "running", targetInfo: null, blind: false,
      startedAt: null, finishedAt: null, lastEventTs: null,
      molecules: {}, reactions: {}, prov: {}, provOrder: [], agents: {}, agentOrder: [],
      cost: EMPTY_COST, verdict: null, report: null, summary: null,
      tab: "result", selectedStep: null, selectedNode: null, selectedMolecule: null,
    }),

  apply: (kind, data, ts) => {
    const s = get();
    // elapsed time comes from event timestamps, so a replay reports the
    // original run's duration rather than the replay's
    if (ts) set({ lastEventTs: ts, startedAt: s.startedAt ?? ts });
    switch (kind) {
      case "run.status": {
        const patch: Partial<RunState> = { status: data.status, target: data.target ?? s.target };
        if (data.blind !== undefined) patch.blind = data.blind;
        if (data.started_at) patch.startedAt = data.started_at;
        if (data.target_info) patch.targetInfo = data.target_info;
        if (data.summary) patch.summary = data.summary;
        if (data.status === "done" || data.status === "failed") {
          patch.finishedAt = ts ?? Date.now() / 1000;
        }
        set(patch);
        break;
      }
      case "agent.status": {
        const prev = s.agents[data.agent_id];
        set({
          agents: {
            ...s.agents,
            [data.agent_id]: { ...data, logs: prev?.logs ?? [] },
          },
          agentOrder: prev ? s.agentOrder : [...s.agentOrder, data.agent_id],
        });
        break;
      }
      case "agent.log": {
        const prev = s.agents[data.agent_id] ?? {
          agent_id: data.agent_id, agent_type: data.agent_id, label: data.agent_id,
          status: "running" as const, message: "", logs: [],
        };
        set({
          agents: {
            ...s.agents,
            [data.agent_id]: {
              ...prev,
              logs: [...prev.logs, { text: data.text, level: data.level, ts: Date.now() / 1000 }].slice(-80),
            },
          },
          agentOrder: s.agents[data.agent_id] ? s.agentOrder : [...s.agentOrder, data.agent_id],
        });
        break;
      }
      case "prov.node": {
        const exists = !!s.prov[data.id];
        const merged = exists
          ? {
              ...s.prov[data.id], ...data,
              parent_ids: Array.from(new Set([...s.prov[data.id].parent_ids, ...data.parent_ids])),
              details: { ...s.prov[data.id].details, ...data.details },
            }
          : data;
        set({
          prov: { ...s.prov, [data.id]: merged },
          provOrder: exists ? s.provOrder : [...s.provOrder, data.id],
        });
        if (data.id === "verdict:route") set({ verdict: data.details as RouteVerdict });
        break;
      }
      case "graph.molecule":
        set({ molecules: { ...s.molecules, [data.id]: data } });
        break;
      case "graph.reaction":
        set({ reactions: { ...s.reactions, [data.id]: data } });
        break;
      case "cost":
        set({ cost: { ...s.cost, ...data } });
        break;
      case "report":
        set({ report: data });
        break;
      default:
        break;
    }
  },

  connect: (runId, replaySpeed = 0) => {
    const es = new EventSource(`/api/runs/${runId}/events?replay_speed=${replaySpeed}`);
    const kinds = [
      "run.status", "agent.status", "agent.log", "prov.node",
      "graph.molecule", "graph.reaction", "route", "cost", "report",
    ];
    for (const kind of kinds) {
      es.addEventListener(kind, (e) => {
        const payload = JSON.parse((e as MessageEvent).data);
        get().apply(kind, payload.data, payload.ts);
      });
    }
    es.addEventListener("end", () => es.close());
    es.onerror = () => es.close();
    return () => es.close();
  },
}));

// ---------------------------------------------------------------- selectors

/** Steps of the chosen route, in execution order, with live grades. */
export function routeSteps(s: RunState) {
  const ids = s.verdict?.route ?? [];
  return ids.map((id, i) => {
    const sv = s.verdict?.steps.find((x) => x.hypothesis_id === id);
    const rx = s.reactions[id];
    const node = s.prov[`verdict:${id}`];
    return {
      index: i + 1,
      id,
      reaction: sv?.reaction ?? (rx ? describeReaction(s, rx) : id),
      grade: (sv?.grade ?? node?.details?.grade ?? "none") as string,
      score: sv?.precedent_score ?? node?.details?.precedent_score ?? null,
      classes: rx?.classes ?? [],
      objections: sv?.objections ?? [],
      critic: rx?.critic ?? null,
    };
  });
}

export function describeReaction(s: RunState, rx: Reaction) {
  const name = (id: string) => s.molecules[id]?.name ?? id;
  return `${rx.reactants.map(name).join(" + ")} → ${name(rx.products[0])}`;
}

/** Provenance nodes that support one route step, grouped by type.
 *  Structure resolutions are facts about molecules rather than about a step,
 *  so they are pulled in by the step's own molecules. */
export function chainForStep(s: RunState, stepId: string) {
  const nodes = s.provOrder.map((id) => s.prov[id]).filter((n) => n && n.step_id === stepId);
  const rx = s.reactions[stepId];
  if (rx) {
    for (const molId of [...rx.reactants, ...rx.products]) {
      const node = s.prov[`res:${molId}`];
      if (node && !nodes.includes(node)) nodes.push(node);
    }
  }
  const byType: Record<string, typeof nodes> = {};
  for (const n of nodes) (byType[n.node_type] ||= []).push(n);
  return { nodes, byType };
}

export function sourceCount(s: RunState, stepId: string) {
  const { byType } = chainForStep(s, stepId);
  return new Set((byType["precedent"] ?? []).map((n) => n.details?.observed_reaction)).size;
}

export function elapsed(s: RunState) {
  if (!s.startedAt) return 0;
  const end = s.finishedAt ?? s.lastEventTs ?? Date.now() / 1000;
  return Math.max(0, end - s.startedAt);
}

/** A readable name even when the target was given as a bare SMILES. */
export function targetName(s: RunState) {
  const t = s.targetInfo;
  if (!t) return s.target || "target";
  if (t.known || (t.name && t.name !== "Target")) return t.name;
  return (t.description?.formula as string) ?? "new compound";
}
