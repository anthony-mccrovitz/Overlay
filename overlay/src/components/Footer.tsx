import Link from "next/link";

export function Footer() {
  return (
    <footer style={{ borderTop: "1px solid var(--border)", padding: "32px 20px", marginTop: 48 }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 16,
            fontSize: 12,
            color: "var(--text-muted)",
          }}
        >
          <div>© {new Date().getFullYear()} Overlay. All rights reserved.</div>
          <div style={{ display: "flex", gap: 20 }}>
            <Link href="/terms" style={{ color: "var(--text-muted)", textDecoration: "none" }}>Terms</Link>
            <Link href="/privacy" style={{ color: "var(--text-muted)", textDecoration: "none" }}>Privacy</Link>
            <a href="mailto:anthonymccrovitz02@gmail.com" style={{ color: "var(--text-muted)", textDecoration: "none" }}>Contact</a>
          </div>
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            lineHeight: 1.6,
            borderTop: "1px solid var(--border)",
            paddingTop: 16,
          }}
        >
          <strong style={{ color: "var(--text-secondary)" }}>Disclaimer:</strong> Overlay is an
          informational sports-analytics subscription. Content is provided for entertainment and
          educational purposes only and does not constitute gambling, financial, or investment
          advice. Overlay does not accept, place, or facilitate wagers. Users are solely responsible
          for compliance with all applicable laws in their jurisdiction. If you or someone you know
          has a gambling problem, call 1-800-GAMBLER. Must be 21+ where applicable.
        </div>
      </div>
    </footer>
  );
}
