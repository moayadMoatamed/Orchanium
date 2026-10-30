/** Single source of truth for the visual language (see design spec).
 *  Monochrome first. The accent means "live / target". Green and red appear
 *  only on verdicts. Graph nodes are told apart by SHAPE, not colour. */

export const C = {
  ground: "#F5F3EE",
  surface: "#FFFFFF",
  hairline: "#E2DED5",
  ink: "#1C1B19",
  muted: "#6B675F",
  accent: "#1F4E8C",
  verified: "#2E7D4F",
  rejected: "#B4402F",
  warning: "#A86A00",
} as const;

/** Verdict for the whole route. */
export const VERDICT = {
  Feasible: { tone: "good", note: "Every step has published precedent." },
  Plausible: { tone: "good", note: "Supported, with weak points to test." },
  Uncertain: { tone: "warn", note: "At least one step has no precedent." },
  Unlikely: { tone: "bad", note: "Evidence argues against this route." },
} as const;
export type VerdictLabel = keyof typeof VERDICT;

/** Evidence grade for one step (computed from precedent similarity). */
export const GRADE = {
  direct: { label: "Verified", tone: "good", blurb: "published for this exact reaction" },
  analog: { label: "Supported", tone: "good", blurb: "published on closely related molecules" },
  weak: { label: "Thin", tone: "warn", blurb: "only loosely related precedent" },
  none: { label: "No precedent", tone: "warn", blurb: "nothing published was found" },
  blocked: { label: "Ruled out", tone: "bad", blurb: "failed a chemistry check" },
} as const;
export type Grade = keyof typeof GRADE;

export const TONE: Record<string, { fg: string; bg: string; border: string }> = {
  good: { fg: C.verified, bg: "rgba(46,125,79,.08)", border: "rgba(46,125,79,.35)" },
  warn: { fg: C.warning, bg: "rgba(168,106,0,.08)", border: "rgba(168,106,0,.32)" },
  bad: { fg: C.rejected, bg: "rgba(180,64,47,.07)", border: "rgba(180,64,47,.35)" },
  neutral: { fg: C.muted, bg: "transparent", border: C.hairline },
  live: { fg: C.accent, bg: "rgba(31,78,140,.07)", border: "rgba(31,78,140,.35)" },
};

/** Status of a single provenance node / check. */
export const STATUS_TONE: Record<string, keyof typeof TONE> = {
  pass: "good",
  warn: "warn",
  fail: "bad",
  skip: "neutral",
  pending: "neutral",
  running: "live",
};

/** Shapes for graph nodes — the meaning never depends on colour alone. */
export type NodeShape = "target" | "literature" | "proposed" | "purchasable" | "reaction" | "rejected";
export const SHAPE_LEGEND: { shape: NodeShape; label: string }[] = [
  { shape: "target", label: "Target" },
  { shape: "literature", label: "From literature" },
  { shape: "proposed", label: "Proposed" },
  { shape: "purchasable", label: "Buyable" },
  { shape: "reaction", label: "Reaction" },
  { shape: "rejected", label: "Ruled out" },
];

/** Chain node types, in the order a reader should follow them. */
export const CHAIN_TYPES: Record<string, { label: string; icon: string; order: number }> = {
  hypothesis: { label: "Proposed step", icon: "◇", order: 0 },
  query: { label: "Search", icon: "⌕", order: 1 },
  source: { label: "Source", icon: "▤", order: 2 },
  extraction: { label: "Reported reaction", icon: "❝", order: 3 },
  citation: { label: "Citation check", icon: "⚓", order: 4 },
  resolution: { label: "Structure", icon: "⬡", order: 5 },
  vision: { label: "Figure read", icon: "👁", order: 6 },
  precedent: { label: "Precedent match", icon: "≈", order: 7 },
  check: { label: "Chemistry check", icon: "✓", order: 8 },
  agreement: { label: "Cross-source", icon: "⇉", order: 9 },
  debate: { label: "Debate", icon: "⚖", order: 10 },
  verdict: { label: "Verdict", icon: "★", order: 11 },
};

export const AGENT_LABEL: Record<string, string> = {
  planner: "Planner",
  decomposer: "Decomposer",
  uspto: "Patent index",
  citation_checker: "Citation checker",
  critic: "Chemistry critic",
  resolver: "Structure resolver",
  builder: "Builder",
  skeptic: "Skeptic",
  debate: "Debate",
  verdict: "Verdict",
  reporter: "Reporter",
  graph: "Graph",
  orchestrator: "Orchestrator",
};
