import type { TickerItem } from "@/lib/feed";

export function TickerBar({ items }: { items: TickerItem[] }) {
  if (!items || items.length === 0) return null;
  const doubled = [...items, ...items];
  return (
    <div className="ticker">
      <div className="ticker-track mono">
        {doubled.map((it, i) => {
          const win = it.result === "W";
          const loss = it.result === "L";
          const cls = win ? "pos" : loss ? "neg" : "";
          const sign = it.units > 0 ? "+" : "";
          return (
            <span key={i} className="ticker-item">
              <span className="ticker-tag">[{it.sport}]</span>
              <span style={{ color: "var(--text-secondary)" }}>{it.matchup}</span>
              <span className={cls}>{it.result}</span>
              <span className={cls}>{sign}{it.units.toFixed(1)}U</span>
              <span style={{ color: "var(--text-muted)" }}>·</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}
