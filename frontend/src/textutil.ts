/** Agent prose cites graph node ids so code can verify the claims. Those ids
 *  are noise to a reader, so UI text strips them and keeps the argument. */
const GRAPH_ID = /\b(?:obs|hyp|web|uspto|clue|prec|res|cite|src|chk)[:_][A-Za-z0-9:_-]+/g;

export function readable(text: string, max = 160): string {
  const clean = (text ?? "")
    .replace(GRAPH_ID, "")
    .replace(/\(\s*[,;]?\s*\)/g, "")
    .replace(/\s+([,.;:])/g, "$1")
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
