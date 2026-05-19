import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions, isAllowlisted } from "@/lib/auth";

export default async function AccountPage() {
  const session = await getServerSession(authOptions);
  if (!session?.user?.email) redirect("/login");

  const active = isAllowlisted(session.user.email);

  return (
    <div style={{ maxWidth: 520, display: "flex", flexDirection: "column", gap: 20 }}>
      <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)", margin: 0 }}>Account</h1>
      <div className="stat-card">
        <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Email</div>
        <div style={{ fontSize: 16, color: "var(--text-bright)", marginTop: 4 }}>{session.user.email}</div>
      </div>
      <div className="stat-card">
        <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Status</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: active ? "var(--green-hi)" : "var(--amber)", marginTop: 4 }}>
          {active ? "Active subscriber" : "Not subscribed"}
        </div>
      </div>
      <p style={{ fontSize: 12, color: "var(--text-muted)" }}>
        Need to cancel or update payment? Email{" "}
        <a href="mailto:anthonymccrovitz02@gmail.com" style={{ color: "var(--indigo)" }}>
          anthonymccrovitz02@gmail.com
        </a>{" "}
        and we&apos;ll handle it within 24 hours.
      </p>
    </div>
  );
}
