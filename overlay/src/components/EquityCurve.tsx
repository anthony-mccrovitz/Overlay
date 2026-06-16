import type { EquityPoint } from "@/lib/feed";

export function EquityCurve({ data, height = 280 }: { data: EquityPoint[]; height?: number }) {
  if (!data || data.length < 2) {
    return (
      <div
        style={{
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-muted)",
          fontSize: 13,
        }}
      >
        Equity curve will appear here once more picks settle.
      </div>
    );
  }
  const width = 1000;
  const padX = 16;
  const padY = 24;
  const xs = data.map((_, i) => i);
  const ys = data.map((d) => d.units);
  const minY = Math.min(0, ...ys);
  const maxY = Math.max(0, ...ys) || 1;
  const sx = (i: number) => padX + (i / (data.length - 1)) * (width - 2 * padX);
  const sy = (y: number) =>
    height - padY - ((y - minY) / (maxY - minY || 1)) * (height - 2 * padY);

  const linePath = xs.map((i) => `${i === 0 ? "M" : "L"} ${sx(i)} ${sy(ys[i])}`).join(" ");
  const areaPath = `${linePath} L ${sx(xs.length - 1)} ${height - padY} L ${sx(0)} ${height - padY} Z`;

  // gridlines (4 horizontal)
  const gridYs = [0.25, 0.5, 0.75].map((p) => padY + p * (height - 2 * padY));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }}>
      <defs>
        <linearGradient id="eq-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#12C58A" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#12C58A" stopOpacity="0" />
        </linearGradient>
      </defs>
      {gridYs.map((y, i) => (
        <line
          key={i}
          x1={padX}
          x2={width - padX}
          y1={y}
          y2={y}
          stroke="#1F232C"
          strokeDasharray="3 4"
        />
      ))}
      <line
        x1={padX}
        x2={width - padX}
        y1={sy(0)}
        y2={sy(0)}
        stroke="#2A2F3A"
        strokeDasharray="2 3"
      />
      <path d={areaPath} fill="url(#eq-fill)" />
      <path d={linePath} fill="none" stroke="#2FE0A3" strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  );
}
