"use client";

import { useState } from "react";

/**
 * Free-list email capture. Posts to /api/lead, which adds the address to the
 * Resend audience and sends a welcome email. Styled to match the /login form.
 * Reusable: drop it anywhere with a `source` tag for attribution.
 */
export function LeadCapture({
  source = "landing",
  cta = "Get free plays",
}: {
  source?: string;
  cta?: string;
}) {
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState(""); // honeypot
  const [state, setState] = useState<"idle" | "submitting" | "done" | "error">("idle");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (state === "submitting") return;
    setState("submitting");
    try {
      const r = await fetch("/api/lead", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, source, company }),
      });
      if (!r.ok) {
        setState("error");
        return;
      }
      setState("done");
    } catch {
      setState("error");
    }
  }

  if (state === "done") {
    return (
      <div
        className="panel"
        style={{
          padding: "18px 22px",
          maxWidth: 460,
          margin: "0 auto",
          textAlign: "center",
          borderColor: "rgba(18,197,138,0.35)",
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--accent-hi)" }}>You&apos;re in. ✓</div>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.6, margin: "6px 0 0" }}>
          Check your inbox — your first free play lands before the next big slate.
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      style={{ display: "flex", gap: 10, maxWidth: 460, margin: "0 auto", flexWrap: "wrap", justifyContent: "center" }}
    >
      {/* honeypot — hidden from humans, catnip for bots */}
      <input
        type="text"
        name="company"
        tabIndex={-1}
        autoComplete="off"
        value={company}
        onChange={(e) => setCompany(e.target.value)}
        style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }}
        aria-hidden="true"
      />
      <input
        type="email"
        required
        placeholder="you@example.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        style={{
          flex: "1 1 240px",
          background: "var(--bg-raised)",
          border: "1px solid var(--border-hi)",
          color: "var(--text-bright)",
          padding: "13px 15px",
          borderRadius: 4,
          fontSize: 14,
          minWidth: 0,
        }}
      />
      <button type="submit" disabled={state === "submitting" || !email} className="btn-primary" style={{ flex: "0 0 auto" }}>
        {state === "submitting" ? "Adding…" : cta}
      </button>
      {state === "error" && (
        <div style={{ flexBasis: "100%", textAlign: "center", color: "var(--red-hi)", fontSize: 12, marginTop: 4 }}>
          Enter a valid email and try again.
        </div>
      )}
    </form>
  );
}
