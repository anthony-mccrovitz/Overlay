import Link from "next/link";

export function Header() {
  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        background: "rgba(7,9,15,0.85)",
        backdropFilter: "blur(8px)",
        position: "sticky",
        top: 0,
        zIndex: 50,
      }}
    >
      <div
        style={{
          maxWidth: 1100,
          margin: "0 auto",
          padding: "14px 20px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Link href="/" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 18,
              fontWeight: 800,
              letterSpacing: "-0.02em",
              background: "linear-gradient(90deg, var(--indigo), var(--violet))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            OVERLAY
          </span>
        </Link>
        <nav style={{ display: "flex", gap: 24, alignItems: "center" }}>
          <Link href="/picks" style={{ color: "var(--text-secondary)", textDecoration: "none", fontSize: 13, fontWeight: 500 }}>
            Picks
          </Link>
          <Link href="/record" style={{ color: "var(--text-secondary)", textDecoration: "none", fontSize: 13, fontWeight: 500 }}>
            Record
          </Link>
          <Link href="/account" style={{ color: "var(--text-secondary)", textDecoration: "none", fontSize: 13, fontWeight: 500 }}>
            Account
          </Link>
        </nav>
      </div>
    </header>
  );
}
