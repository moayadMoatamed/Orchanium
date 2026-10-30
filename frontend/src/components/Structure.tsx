import { useEffect, useState } from "react";

const cache = new Map<string, string>();

/** 2D depiction rendered by RDKit on the backend (never by the model). */
export function Structure({
  smiles, width = 260, height = 190, className = "", framed = true,
}: { smiles: string; width?: number; height?: number; className?: string; framed?: boolean }) {
  const key = `${smiles}|${width}x${height}`;
  const [svg, setSvg] = useState<string | null>(cache.get(key) ?? null);

  useEffect(() => {
    if (!smiles || cache.has(key)) {
      setSvg(cache.get(key) ?? null);
      return;
    }
    let alive = true;
    fetch(`/api/depict?smiles=${encodeURIComponent(smiles)}&width=${width}&height=${height}`)
      .then((r) => (r.ok ? r.text() : null))
      .then((t) => {
        if (!t || !alive) return;
        cache.set(key, t);
        setSvg(t);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [smiles, key, width, height]);

  const frame = framed ? "rounded-chip border border-hairline bg-surface" : "";
  if (!svg) {
    return (
      <div className={`grid place-items-center ${frame} ${className}`} style={{ width, height }}>
        <span className="text-[12px] text-muted/60">structure</span>
      </div>
    );
  }
  return (
    <div
      className={`grid place-items-center ${frame} ${className}`}
      style={{ width, height }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
