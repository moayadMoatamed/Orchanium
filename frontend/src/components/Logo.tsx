/** Orchanium's mark: element 119, the next one nobody has made.
 *  The product is for compounds that do not exist yet, so the logo is one. */
export function Mark({ size = 26, radius = 5, tile = "#1C1B19", face = "#F5F3EE", rule = "#1F4E8C" }: {
  size?: number; radius?: number; tile?: string; face?: string; rule?: string;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden className="shrink-0">
      <rect x="0" y="0" width="48" height="48" rx={radius} fill={tile} />
      <text
        x="7" y="14"
        fill={face}
        fontSize="8.5"
        fontWeight="500"
        fontFamily="IBM Plex Mono, ui-monospace, monospace"
        opacity="0.75"
      >
        119
      </text>
      <text
        x="24" y="34.5"
        fill={face}
        fontSize="21"
        fontWeight="700"
        letterSpacing="-0.5"
        textAnchor="middle"
        fontFamily="IBM Plex Sans, system-ui, sans-serif"
      >
        Or
      </text>
      <rect x="17" y="39" width="14" height="2.4" rx="1.2" fill={rule} />
    </svg>
  );
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2.5 pr-1">
      <Mark size={size} />
      <span className="text-[17px] font-semibold tracking-[-0.01em]">Orchanium</span>
    </div>
  );
}
