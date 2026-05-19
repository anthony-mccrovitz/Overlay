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
        style={{
          maxWidth: 1280,
          margin: "0 auto",
          padding: "16px 24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Link href="/" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 10 }}>
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
        <nav style={{ display: "flex", gap: 28, alignItems: "center" }}>
          <Link href="/picks" style={navLink}>Picks</Link>
          <Link href="/models" style={navLink}>Models</Link>
          <Link href="/tools" style={navLink}>Tools</Link>
          <Link href="/record" style={navLink}>Record</Link>
          <a
            href={process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "#pricing"}
            className="btn-ghost"
            style={{ padding: "8px 16px", fontSize: 12 }}
          >
            Subscribe — $29/mo
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
