import { redirect } from "next/navigation";
import { getSession, isAllowlisted } from "@/lib/session";
import { readFeed } from "@/lib/feed";
import { PickCard } from "@/components/PickCard";
import { SubscribeButton } from "@/components/SubscribeButton";

export const dynamic = "force-dynamic";

export default async function PicksPage() {
  const session = getSession();
  if (!session?.email) redirect("/login");
  if (!isAllowlisted(session.email)) {
    return (
      <div style={{ maxWidth: 520, margin: "80px auto", textAlign: "center", padding: "0 20px" }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, color: "var(--text-bright)", marginBottom: 12 }}>
          You&apos;re not subscribed yet
        </h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: 20 }}>
          {session.email} isn&apos;t on the subscriber list. Subscribe below — once your payment
          is confirmed, your access unlocks within an hour.
        </p>
        <SubscribeButton />
      </div>
    );
  }

  const feed = await readFeed();
  if (!feed) {
    return (
      <div style={containerStyle}>
        <p style={{ color: "var(--text-secondary)" }}>No picks file found. Check back shortly.</p>
      </div>
    );
  }

  const allSports = Object.entries(feed.picks).filter(([, picks]) => picks.length > 0);
  const total = allSports.reduce((sum, [, picks]) => sum + picks.length, 0);

  return (
    <div style={containerStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div className="eyebrow">Today&apos;s card</div>
          <h1 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 0", letterSpacing: "-0.015em" }}>
            {fmtDate(feed.date)}
          </h1>
          <div className="mono" style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6, letterSpacing: "0.06em" }}>
            {total} PICK{total === 1 ? "" : "S"} · LIVE · LOGGED AT POST
          </div>
        </div>
        <div className="label-muted" style={{ alignSelf: "center" }}>signed in: {session.email}</div>
      </div>

      {allSports.map(([sport, picks]) => (
        <Section key={sport} title={sport.toUpperCase()} picks={picks} />
      ))}
      {total === 0 && (
        <div className="panel" style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>
          No card picks posted yet for today. Check back after the morning slate locks.
        </div>
      )}
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  maxWidth: 1100,
  margin: "0 auto",
  padding: "32px 24px",
  display: "flex",
  flexDirection: "column",
  gap: 28,
};

function Section({ title, picks }: { title: string; picks: any[] }) {
  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <span className="mono" style={{ color: "var(--accent-hi)", fontSize: 12, fontWeight: 800, letterSpacing: "0.12em" }}>
          [{title}]
        </span>
        <span style={{ color: "var(--text-bright)", fontWeight: 700, fontSize: 14 }}>
          {picks.length} pick{picks.length === 1 ? "" : "s"}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
        {picks.map((p, i) => (
          <PickCard key={i} pick={p} />
        ))}
      </div>
    </section>
  );
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso + "T12:00:00");
    return d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  } catch {
    return iso;
  }
}
