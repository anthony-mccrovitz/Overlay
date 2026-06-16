// Inline SVG icons for the World Cup UI — no emoji. currentColor + size prop so
// they inherit text color and scale cleanly. Plain components: server + client safe.

type P = { size?: number; color?: string; style?: React.CSSProperties };

const base = (size: number, color?: string, style?: React.CSSProperties): React.SVGProps<SVGSVGElement> => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none",
  stroke: color || "currentColor", strokeWidth: 2, strokeLinecap: "round",
  strokeLinejoin: "round", style: { flexShrink: 0, ...style },
});

/** Host / home-venue marker (stadium-ish location pin with a roof). */
export function IconHost({ size = 13, color, style }: P) {
  return (
    <svg {...base(size, color, style)}>
      <path d="M3 9l9-6 9 6" />
      <path d="M4 10v9h16v-9" />
      <path d="M9 19v-5h6v5" />
    </svg>
  );
}

/** Altitude / mountain. */
export function IconAltitude({ size = 13, color, style }: P) {
  return (
    <svg {...base(size, color, style)}>
      <path d="M3 20h18L14 6l-3.5 6-2-3z" />
    </svg>
  );
}

/** Penalty taker — a circle with a P, drawn (not the ⓟ glyph). */
export function IconPenalty({ size = 13, color, style }: P) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0, ...style }}>
      <circle cx="12" cy="12" r="10" stroke={color || "currentColor"} strokeWidth="2" />
      <path d="M9 17V7h3.2a3 3 0 0 1 0 6H9" stroke={color || "currentColor"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Trophy. */
export function IconTrophy({ size = 14, color, style }: P) {
  return (
    <svg {...base(size, color, style)}>
      <path d="M8 21h8" /><path d="M12 17v4" />
      <path d="M7 4h10v5a5 5 0 0 1-10 0V4z" />
      <path d="M7 6H4v2a3 3 0 0 0 3 3" /><path d="M17 6h3v2a3 3 0 0 1-3 3" />
    </svg>
  );
}

/** Football / soccer ball. */
export function IconBall({ size = 14, color, style }: P) {
  return (
    <svg {...base(size, color, style)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7l3.5 2.5-1.3 4.1h-4.4L8.5 9.5 12 7z" />
    </svg>
  );
}

/** Lock — for gated/premium content. */
export function IconLock({ size = 14, color, style }: P) {
  return (
    <svg {...base(size, color, style)}>
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}
