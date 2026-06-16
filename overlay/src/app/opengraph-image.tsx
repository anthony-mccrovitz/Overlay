import { ImageResponse } from "next/og";

// Branded social-share card. Rendered when an Overlay link is posted to
// Twitter / Reddit / iMessage / Discord — the product's main organic channel.
// Numbers are deliberately evergreen so the card never goes stale.

export const runtime = "edge";
export const alt = "Overlay — ML sports betting edge detection";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          position: "relative",
          background:
            "linear-gradient(135deg, #0E1714 0%, #0A0B0D 42%, #0A0B0D 100%)",
          padding: "72px 80px",
          fontFamily: "sans-serif",
        }}
      >
        {/* accent top edge */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: 8,
            background: "linear-gradient(90deg, #12C58A, #0EA98F, #34D399)",
          }}
        />
        {/* top edge accent */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            color: "#12C58A",
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: "0.22em",
          }}
        >
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: 999,
              background: "#12C58A",
            }}
          />
          OVERLAY
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              fontSize: 68,
              fontWeight: 800,
              color: "#F2F4F8",
              lineHeight: 1.08,
              letterSpacing: "-0.02em",
              maxWidth: 980,
            }}
          >
            <div style={{ display: "flex" }}>Quant-backed picks</div>
            <div style={{ display: "flex" }}>
              <span>for the</span>
              <span style={{ color: "#12C58A", margin: "0 20px" }}>1%</span>
              <span>of bettors.</span>
            </div>
          </div>
          <div
            style={{
              fontSize: 30,
              color: "#8A93A3",
              lineHeight: 1.45,
              maxWidth: 900,
            }}
          >
            A three-model ensemble finds positive EV in NBA &amp; MLB lines.
            Every pick timestamped before tip-off, tracked in public.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            gap: 56,
            fontSize: 24,
            color: "#5A6171",
            letterSpacing: "0.04em",
          }}
        >
          <div style={{ display: "flex", gap: 12 }}>
            <span style={{ color: "#12C58A", fontWeight: 700 }}>XGBoost</span>
            <span>·</span>
            <span style={{ color: "#12C58A", fontWeight: 700 }}>LightGBM</span>
            <span>·</span>
            <span style={{ color: "#12C58A", fontWeight: 700 }}>CatBoost</span>
          </div>
          <div>Public ledger · No touts · No parlays</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
