import Link from "next/link";

export function Header() {
  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        background: "var(--bg)",
        position: "sticky",
        top: 44,
        zIndex: 40,
      }}
    >
      <div
        className="header-inner"
        style={{
          maxWidth: 1280,
          margin: "0 auto",
          padding: "16px 24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <Link href="/" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span
            style={{
              width: 22,
              height: 22,
              background: "var(--accent)",
              borderRadius: 3,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              color: "white",
              fontWeight: 800,
              fontSize: 13,
              fontFamily: "var(--font-mono)",
            }}
          >
            O
          </span>
          <span
            style={{
              fontSize: 15,
              fontWeight: 800,
              letterSpacing: "0.08em",
              color: "var(--text-bright)",
            }}
          >
            OVERLAY
          </span>
        </Link>

        {/* Desktop nav */}
        <nav className="nav-desktop" style={{ display: "flex", gap: 28, alignItems: "center" }}>
          <Link href="/picks" style={navLink}>Picks</Link>
          <Link href="/slate" style={navLink}>Slate</Link>
          <Link href="/models" style={navLink}>Models</Link>
          <Link href="/tools" style={navLink}>Tools</Link>
          <Link href="/record" style={navLink}>Record</Link>
          <a
            href={process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "#pricing"}
            className="btn-ghost"
            style={{ padding: "8px 16px", fontSize: 12 }}
            target="_blank"
            rel="noopener noreferrer"
          >
            Subscribe — $29/mo
          </a>
        </nav>

        {/* Mobile nav — compact horizontal scrollable strip */}
        <nav
          className="nav-mobile"
          style={{
            display: "none",
            alignItems: "center",
            gap: 14,
            overflowX: "auto",
            WebkitOverflowScrolling: "touch",
            flex: 1,
            justifyContent: "flex-end",
            scrollbarWidth: "none",
          }}
        >
          <Link href="/picks" style={navLinkMobile}>Picks</Link>
          <Link href="/slate" style={navLinkMobile}>Slate</Link>
          <Link href="/models" style={navLinkMobile}>Models</Link>
          <Link href="/tools" style={navLinkMobile}>Tools</Link>
          <Link href="/record" style={navLinkMobile}>Record</Link>
          <a
            href={process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "#pricing"}
            className="btn-primary"
            style={{ padding: "6px 12px", fontSize: 11, flexShrink: 0 }}
            target="_blank"
            rel="noopener noreferrer"
          >
            $29/mo
          </a>
        </nav>
      </div>
    </header>
  );
}

const navLink: React.CSSProperties = {
  color: "var(--text-secondary)",
  textDecoration: "none",
  fontSize: 13,
  fontWeight: 500,
};

const navLinkMobile: React.CSSProperties = {
  color: "var(--text-secondary)",
  textDecoration: "none",
  fontSize: 12,
  fontWeight: 600,
  flexShrink: 0,
  letterSpacing: "0.02em",
};
