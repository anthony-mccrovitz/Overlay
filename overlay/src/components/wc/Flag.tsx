import { flagUrl, code } from "@/lib/wc";

/**
 * Country flag as a crisp SVG (flagcdn), with a rounded frame. Plain
 * presentational component — safe in both server and client components.
 * Falls back to a 3-letter code chip when no flag is mapped.
 */
export function Flag({ team, size = 14, title = true }: { team: string; size?: number; title?: boolean }) {
  const url = flagUrl(team);
  const w = Math.round((size * 4) / 3);
  const frame: React.CSSProperties = {
    display: "inline-block",
    width: w,
    height: size,
    borderRadius: 2,
    overflow: "hidden",
    flexShrink: 0,
    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.12)",
    verticalAlign: "middle",
  };
  if (!url) {
    return (
      <span className="mono" style={{ ...frame, width: "auto", padding: "0 4px", fontSize: size - 4, fontWeight: 700, color: "var(--text-muted)", background: "var(--bg-overlay)", lineHeight: `${size}px`, textAlign: "center" }}>
        {code(team)}
      </span>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return (
    <img
      src={url}
      alt={title ? team : ""}
      title={title ? team : undefined}
      loading="lazy"
      width={w}
      height={size}
      style={{ ...frame, objectFit: "cover" }}
    />
  );
}
