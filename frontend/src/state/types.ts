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
  lab_successes?: number;
  lab_failures?: number;
  objections: Objection[];
}

export interface Objection {
  id: string;
  hypothesis_id?: string;
  severity: string;
  plain?: string;
  claim: string;
  cited_ids?: string[];
}

export type Basis = "lab" | "reported" | "analog" | "suggested" | "missing";

export interface ConditionField {
  value: string | null;
  basis: Basis;
  source?: string;
  url?: string | null;
  n?: number;
  range?: string;
}

export interface Operation {
  kind: "protect" | "activate" | "react" | "deprotect" | "workup" | "purify";
  action: string;
  reagents: string[];
  why: string;
  responds_to: string | null;
  responds_to_text: string | null;
  backed: boolean;
}

export interface LabNoteRecord {
  id: string;
  outcome: "success" | "failure";
  yield_pct: number | null;
  conditions: Record<string, any>;
  reagents: string[];
  observations: string | null;
  title: string;
}

export interface Revision {
  note_id: string;
  step_id: string;
  outcome: "success" | "failure";
  changes: string[];
  at: number;
  before: { label: string; confidence: number };
  after: { label: string; confidence: number };
}

export interface LabNoteInput {
  step_id: string;
  outcome: "success" | "failure";
  yield_pct?: number | null;
  reagents?: string[];
  solvent?: string | null;
  temperature_c?: number | null;
  time?: string | null;
  scale?: string | null;
  observations?: string | null;
  notes?: string | null;
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
    lab_successes?: number;
    lab_failures?: number;
    objections: Objection[];
    transformation: string[];
    critic: Record<string, string>;
    name?: string | null;
    plain?: string | null;
    procedure?: Operation[];
    conditions?: Record<string, ConditionField>;
    competing_groups?: string | null;
    lab_notes?: LabNoteRecord[];
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
      origin?: string;
      recalled_from?: string | null;
      citation_check: string | null;
    }[];
  }[];
  debate: {
    builder: string[];
    skeptic: string[];
    sustained_objections: Objection[];
    struck_citations: string[];
  } | null;
  evidence: { clues_by_source: Record<string, number>; recalled?: number; citation_checks: Record<string, number> };
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
