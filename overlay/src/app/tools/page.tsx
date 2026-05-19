import { redirect } from "next/navigation";
import { getSession, isAllowlisted } from "@/lib/session";
import { ToolsClient } from "@/components/tools/ToolsClient";
import { SubscribeButton } from "@/components/SubscribeButton";

export const dynamic = "force-dynamic";

export default async function ToolsPage() {
  const session = getSession();
  if (!session?.email) redirect("/login");
  if (!isAllowlisted(session.email)) {
    return (
      <div style={{ maxWidth: 520, margin: "80px auto", textAlign: "center", padding: "0 20px" }}>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)", marginBottom: 12 }}>
          Subscriber tools
        </h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: 20 }}>
          EV calc, CLV calc, odds converter, parlay builder. Unlocked with the founding subscription.
        </p>
        <SubscribeButton />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 24px", display: "flex", flexDirection: "column", gap: 24 }}>
      <div>
        <div className="eyebrow">Workbench</div>
        <h1 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 0", letterSpacing: "-0.015em" }}>
          The tools the model uses
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: 8, fontSize: 14, maxWidth: 600 }}>
          EV · CLV · odds conversion · parlay math. Everything wired to American, decimal, fraction,
          and implied — same primitives the ensemble runs on.
        </p>
      </div>
      <ToolsClient />
    </div>
  );
}
