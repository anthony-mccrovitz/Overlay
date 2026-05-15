import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

const SUBSCRIBERS_FILE = path.join(process.cwd(), "..", "data", "subscribers.json");

interface Subscriber {
  email: string;
  tier: string;
  signed_up_at: string;
  source: string;
}

async function readSubscribers(): Promise<Subscriber[]> {
  try {
    const raw = await fs.readFile(SUBSCRIBERS_FILE, "utf-8");
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

async function writeSubscribers(subs: Subscriber[]): Promise<void> {
  await fs.writeFile(SUBSCRIBERS_FILE, JSON.stringify(subs, null, 2), "utf-8");
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const email = (body.email ?? "").trim().toLowerCase();
    const tier  = body.tier ?? "founding";
    const source = body.source ?? "landing";

    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return NextResponse.json({ error: "Invalid email address." }, { status: 400 });
    }

    const subs = await readSubscribers();

    if (subs.some((s) => s.email === email)) {
      return NextResponse.json({ ok: true, message: "Already on the list!" });
    }

    subs.push({ email, tier, signed_up_at: new Date().toISOString(), source });
    await writeSubscribers(subs);

    return NextResponse.json({ ok: true, message: "You're on the list!" });
  } catch (err) {
    console.error("[subscribe]", err);
    return NextResponse.json({ error: "Server error. Try again." }, { status: 500 });
  }
}

export async function GET() {
  return NextResponse.json({ error: "Method not allowed." }, { status: 405 });
}
