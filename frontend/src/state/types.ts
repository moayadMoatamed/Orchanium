export type Status = "pending" | "running" | "pass" | "warn" | "fail" | "skip";

export interface ProvNode {
  id: string;
  parent_ids: string[];
  step_id: string | null;
  node_type: string;
  status: Status;
  summary: string;
  details: Record<string, any>;
  agent_id: string | null;
  verdict?: string | null;
}

export interface Molecule {
  id: string;
  smiles: string;
  name: string;
  roles: string[];
  known: boolean;
  cid: number | null;
  purchasable: boolean;
  purchasable_basis: string;
}

export interface Reaction {
  id: string;
  kind: "hypothesis" | "observed";
  reactants: string[];
  products: string[];
  classes: string[];
  origin: string;
  clue_ids: string[];
  depth: number | null;
  critic: "pass" | "warn" | "block" | null;
}

export interface AgentState {
  agent_id: string;
  agent_type: string;
  label: string;
  status: "idle" | "running" | "done" | "failed";
  message: string;
  logs: { text: string; level: string; ts: number }[];
}

export interface Cost {
  llm_calls: number;
  tokens_in: number;
  tokens_out: number;
  searches: number;
  sam_images: number;
  usd: number;
}

export interface StepVerdict {
  hypothesis_id: string;
  reaction: string;
  grade: string;
  precedent_score: number | null;
  failure_precedents: number;
  objections: { id: string; severity: string; claim: string; cited_ids: string[] }[];
}

export interface RouteVerdict {
  label: string;
  confidence: number;
  reasons: string[];
  route: string[];
  route_source: string;
  steps: StepVerdict[];
  gaps: string[];
}

/** Rich, verified payload the reporter emits at the end of a run. */
export interface ReportData {
  target: string;
  verdict: { label: string; confidence: number; reasons: string[]; route_source: string; gaps: string[] };
  starting_materials: string[];
  steps: {
    hypothesis_id: string;
    reaction: string;
    grade: string;
    precedent_score: number | null;
    failure_precedents: number;
    objections: { id: string; severity: string; claim: string }[];
    transformation: string[];
    critic: Record<string, string>;
    precedents: {
      score: number;
      grade: string;
      outcome: string;
      product_similarity: number;
      transformation_similarity: number;
      reaction: string;
      conditions: Record<string, any>;
      yield_pct: number | null;
      source: string;
      url: string | null;
      citation_check: string | null;
    }[];
  }[];
  debate: {
    builder: string[];
    skeptic: string[];
    sustained_objections: { id: string; hypothesis_id: string; severity: string; claim: string; cited_ids: string[] }[];
    struck_citations: string[];
  } | null;
  evidence: { clues_by_source: Record<string, number>; citation_checks: Record<string, number> };
}

export interface TargetInfo {
  query: string;
  name: string;
  smiles: string;
  inchikey: string;
  cid: number | null;
  known: boolean;
  vendors: number;
  description: Record<string, any>;
}
