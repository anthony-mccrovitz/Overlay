"use client";

import { signIn } from "next-auth/react";
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
  const checkEmail = sp.get("check") === "1";
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    await signIn("email", { email, callbackUrl: "/picks" });
  }

  if (checkEmail) {
    return (
      <div style={{ maxWidth: 420, margin: "60px auto", textAlign: "center" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-bright)" }}>Check your email</h1>
        <p style={{ color: "var(--text-secondary)", marginTop: 12 }}>
          A sign-in link has been sent. Open it on this device.
        </p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 420, margin: "60px auto" }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-bright)" }}>Sign in</h1>
      <p style={{ color: "var(--text-secondary)", marginTop: 8, fontSize: 13 }}>
        Enter the email you used to subscribe. We&apos;ll send you a one-tap magic link.
      </p>
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
            borderRadius: 8,
            fontSize: 14,
          }}
        />
        <button type="submit" disabled={submitting} className="btn-primary">
          {submitting ? "Sending…" : "Send magic link"}
        </button>
      </form>
    </div>
  );
}
