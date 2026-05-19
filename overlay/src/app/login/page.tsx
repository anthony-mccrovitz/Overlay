"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const sp = useSearchParams();
  const error = sp.get("error");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await fetch("/api/auth/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <div style={{ maxWidth: 420, margin: "60px auto", textAlign: "center" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-bright)" }}>Check your email</h1>
        <p style={{ color: "var(--text-secondary)", marginTop: 12, lineHeight: 1.6 }}>
          If <strong style={{ color: "var(--text-bright)" }}>{email}</strong> is an active
          subscription, a one-tap sign-in link is on its way. Open it on this device.
        </p>
        <p style={{ color: "var(--text-muted)", marginTop: 16, fontSize: 12 }}>
          Link expires in 15 minutes.
        </p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 420, margin: "60px auto", padding: "0 20px" }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-bright)" }}>Sign in</h1>
      <p style={{ color: "var(--text-secondary)", marginTop: 8, fontSize: 13, lineHeight: 1.6 }}>
        Enter the email you used to subscribe. We&apos;ll send you a one-tap magic link.
      </p>

      {error === "invalid" && (
        <div style={errorBox}>That sign-in link is invalid or expired. Request a fresh one below.</div>
      )}
      {error === "not_subscribed" && (
        <div style={errorBox}>That email isn&apos;t on the subscriber list. Subscribe first and we&apos;ll flip your access on.</div>
      )}

      <form onSubmit={onSubmit} style={{ marginTop: 24, display: "flex", flexDirection: "column", gap: 12 }}>
        <input
          type="email"
          required
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{
            background: "var(--bg-raised)",
            border: "1px solid var(--border-hi)",
            color: "var(--text-bright)",
            padding: "12px 14px",
            borderRadius: 4,
            fontSize: 14,
          }}
        />
        <button type="submit" disabled={submitting || !email} className="btn-primary">
          {submitting ? "Sending…" : "Send magic link"}
        </button>
      </form>
    </div>
  );
}

const errorBox: React.CSSProperties = {
  marginTop: 16,
  padding: "10px 14px",
  borderRadius: 4,
  background: "var(--red-dim)",
  border: "1px solid rgba(239,68,68,0.35)",
  color: "var(--red-hi)",
  fontSize: 13,
};
