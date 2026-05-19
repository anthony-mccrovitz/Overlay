import { redirect } from "next/navigation";
import { isAllowlisted } from "@/lib/auth";
import { safeSession } from "@/lib/session";
import { readFeed } from "@/lib/feed";
import { PickCard } from "@/components/PickCard";
import { SubscribeButton } from "@/components/SubscribeButton";

export const dynamic = "force-dynamic";

export default async function PicksPage() {
  const session = await safeSession();
  if (!session?.user?.email) redirect("/login");
  if (!isAllowlisted(session.user.email)) {
    return (
      <div style={{ textAlign: "center", padding: "80px 20px" }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, color: "var(--text-bright)", marginBottom: 12 }}>
          You&apos;re not subscribed yet
        </h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: 20 }}>
          {session.user.email} isn&apos;t on the subscriber list. Subscribe below — once your payment
          is confirmed, your access unlocks within an hour.
        </p>
        <SubscribeButton />
      </div>
    );
  }

  const feed = await readFeed();
  if (!feed) {
    return <p style={{ color: "var(--text-secondary)" }}>No picks file found. Check back shortly.</p>;
  }

  const { nba, mlb } = feed.picks;
  const total = nba.length + mlb.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
      <div>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)", margin: 0 }}>
          Today&apos;s card
        </h1>
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4 }}>
          {feed.date} · {total} pick{total === 1 ? "" : "s"}
        </div>
      </div>

      {nba.length > 0 && (
        <Section title="NBA" picks={nba} />
      )}
      {mlb.length > 0 && (
        <Section title="MLB" picks={mlb} />
      )}
      {total === 0 && (
        <p style={{ color: "var(--text-secondary)" }}>
          No card picks posted yet for today. Check back after the morning slate locks.
        </p>
      )}
    </div>
  );
}

function Section({ title, picks }: { title: string; picks: any[] }) {
  return (
    <section>
      <h2 style={{ fontSize: 18, fontWeight: 700, color: "var(--text-bright)", marginBottom: 12 }}>{title}</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
        {picks.map((p, i) => (
          <PickCard key={i} pick={p} />
        ))}
      </div>
    </section>
  );
}
