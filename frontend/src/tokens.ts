/** Single source of truth for the visual language (see design spec).
 *  Monochrome first. The accent means "live / target". Green and red appear
 *  only on verdicts. Every status is an icon plus a word, never colour alone. */

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
  lab: "#6A3E9C",
} as const;

/** Verdict for the whole route, with what it means for the reader. */
export const VERDICT = {
  Feasible: { tone: "good", note: "Every step has been done before in published work." },
  Plausible: { tone: "good", note: "Backed by published work, with a weak point worth testing first." },
  Uncertain: { tone: "warn", note: "At least one step has never been shown to work." },
  Unlikely: { tone: "bad", note: "Published evidence argues against this route." },
} as const;
export type VerdictLabel = keyof typeof VERDICT;

/** Evidence grade for one step (computed from precedent similarity). */
export const GRADE = {
  direct: {
    label: "Verified", tone: "good", blurb: "published for this exact reaction",
    plain: "This exact reaction has been published.",
  },
  analog: {
    label: "Supported", tone: "good", blurb: "published on closely related molecules",
    plain: "The same reaction has been published on very similar molecules.",
  },
  weak: {
    label: "Thin", tone: "warn", blurb: "only loosely related precedent",
    plain: "Only loosely related reactions have been published.",
  },
  none: {
    label: "No precedent", tone: "warn", blurb: "nothing published was found",
    plain: "Nothing published backs this step up.",
  },
  blocked: {
    label: "Ruled out", tone: "bad", blurb: "failed a chemistry check",
    plain: "It fails a chemistry check, so it was ruled out.",
  },
} as const;
export type Grade = keyof typeof GRADE;

export const TONE: Record<string, { fg: string; bg: string; border: string }> = {
  good: { fg: C.verified, bg: "rgba(46,125,79,.08)", border: "rgba(46,125,79,.35)" },
  warn: { fg: C.warning, bg: "rgba(168,106,0,.08)", border: "rgba(168,106,0,.32)" },
  bad: { fg: C.rejected, bg: "rgba(180,64,47,.07)", border: "rgba(180,64,47,.35)" },
  neutral: { fg: C.muted, bg: "transparent", border: C.hairline },
  live: { fg: C.accent, bg: "rgba(31,78,140,.07)", border: "rgba(31,78,140,.35)" },
  /** the user's own lab results: never styled like literature */
  lab: { fg: C.lab, bg: "rgba(106,62,156,.07)", border: "rgba(106,62,156,.35)" },
};

/** Where a condition value came from. */
export const BASIS: Record<string, { word: string; tone: keyof typeof TONE; hint: string }> = {
  lab: { word: "Your lab", tone: "lab", hint: "From your own lab note on this step" },
  reported: { word: "This reaction", tone: "good", hint: "Reported for this exact reaction" },
  analog: { word: "Similar reaction", tone: "neutral", hint: "Reported for a closely related reaction" },
  suggested: { word: "Suggested", tone: "live", hint: "Not reported; the Builder's recommendation from similar reactions" },
  missing: { word: "Not found", tone: "neutral", hint: "No source reported it" },
};

/** The kinds of lab operation a step is made of. */
export const OPERATION: Record<string, { label: string; plain: string }> = {
  protect: { label: "Protect", plain: "Cap a group that would otherwise react" },
  activate: { label: "Activate", plain: "Make a partner reactive enough" },
  react: { label: "Main reaction", plain: "Form the new bond" },
  deprotect: { label: "Deprotect", plain: "Remove the cap again" },
  workup: { label: "Work up", plain: "Stop the reaction and separate the crude product" },
  purify: { label: "Purify", plain: "Isolate the clean product" },
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

/** What each reaction class does, in words a non-chemist can follow.
 *  Unknown classes fall back to their own name. */
export const REACTION_PLAIN: Record<string, string> = {
  "Acyl chloride formation": "Activates an acid so it reacts readily",
  "Alcohol carbonylation (Pd/CO)": "Turns an alcohol into an acid using carbon monoxide",
  "Amide formation (N-acylation)": "Joins an acid and an amine with an amide bond",
  "Aromatic nitration": "Adds a nitro group to a ring",
  "Carbonyl reduction": "Reduces a ketone or aldehyde to an alcohol",
  "Chlorosulfonation": "Adds a sulfonyl chloride handle to a ring",
  "Ester formation (O-acylation)": "Joins an acid and an alcohol with an ester bond",
  "Ether formation (O-alkylation)": "Joins two pieces through an oxygen atom",
  "Friedel-Crafts acylation": "Attaches a carbonyl group to a ring",
  "Kolbe-Schmitt carboxylation": "Adds an acid group to a phenol ring using CO₂",
  "N-alkylation": "Attaches a carbon chain to a nitrogen",
  "Nitrile hydrolysis": "Converts a nitrile into an acid or amide",
  "Nitro reduction": "Turns a nitro group into an amine",
  "Reductive amination": "Joins an amine and a carbonyl into a new C–N bond",
  "Sulfonamide formation": "Joins a sulfonyl chloride and an amine",
  "Suzuki coupling": "Joins two rings with a palladium catalyst",
  "Ester hydrolysis": "Splits an ester back into an acid and an alcohol",
  "Oxime formation": "Converts a carbonyl into an oxime",
  "Oxime dehydration to nitrile": "Converts an oxime into a nitrile",
  "Darzens glycidic ester condensation": "Builds an epoxide next to an ester",
};

export function reactionPlain(cls: string | undefined): string {
  if (!cls) return "A proposed chemical step";
  return REACTION_PLAIN[cls] ?? cls;
}

/** How confident the verdict is, in words. A doubtful verdict never gets a
 *  confident word: "Uncertain · high confidence" tells a reader two opposite
 *  things and makes them trust neither. */
export function confidenceWords(c: number, label?: string): string {
  const doubtful = label === "Uncertain" || label === "Unlikely";
  if (c >= 0.85 && !doubtful) return "high confidence";
  if (c >= 0.65 && !doubtful) return "good confidence";
  if (c >= 0.45) return "moderate confidence";
  return "low confidence";
}

export const AGENT_LABEL: Record<string, string> = {
  planner: "Planner",
  decomposer: "Decomposer",
  uspto: "Patent index",
  memory: "Knowledge graph",
  lab: "Your lab",
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
