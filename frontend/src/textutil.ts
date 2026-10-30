/** Agent prose cites graph node ids so code can verify the claims. Those ids
 *  are noise to a reader, so UI text strips them and keeps the argument. */
const GRAPH_ID = /\b(?:obs|hyp|web|uspto|clue|prec|res|cite|src|chk)[:_][A-Za-z0-9:_-]+/g;
/** Older runs recorded emoji in agent text; the UI uses real icons instead. */
const PICTOGRAPH = /[\p{Extended_Pictographic}\u{FE0F}]/gu;

export function readable(text: string, max = 160): string {
  const clean = (text ?? "")
    .replace(PICTOGRAPH, "")
    .replace(GRAPH_ID, "")
    .replace(/\(\s*[,;]?\s*\)/g, "")
    .replace(/\s+([,.;:])/g, "$1")
    .replace(/[,;]\s*([,;.])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (clean.length <= max) return clean;
  const cut = clean.lastIndexOf(" ", max - 1);
  return `${clean.slice(0, cut > 40 ? cut : max - 1)}…`;
}

/** First clause only — for tight spots like a table row. */
export function firstClause(text: string, max = 110): string {
  const clean = readable(text, 10_000);
  const end = clean.search(/[.;]\s/);
  return readable(end > 24 ? clean.slice(0, end + 1) : clean, max);
}

/** Full stops that do not end a sentence. */
const ABBREVIATION = /\b(?:e\.g|i\.e|etc|vs|approx|ca|cf|incl|ref|eq|equiv|no|fig|al)$/i;

/** The first sentence, used as the short form in MoreText. */
export function firstSentence(text: string, max = 220): string {
  const clean = readable(text, 10_000);
  const stops = /\.\s/g;
  let m: RegExpExecArray | null;
  while ((m = stops.exec(clean))) {
    if (m.index > 24 && !ABBREVIATION.test(clean.slice(0, m.index))) {
      return readable(clean.slice(0, m.index + 1), max);
    }
  }
  return readable(clean, max);
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}
