import { NextRequest, NextResponse } from "next/server";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

const SUBSCRIBERS_FILE = join(process.cwd(), "..", "data", "subscribers.json");

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const email = searchParams.get("email");

  if (!email) {
    return NextResponse.json({ error: "email required" }, { status: 400 });
  }

  try {
    if (existsSync(SUBSCRIBERS_FILE)) {
      const subs = JSON.parse(readFileSync(SUBSCRIBERS_FILE, "utf-8"));
      const sub = subs[email.toLowerCase()];
      if (sub?.active) {
        return NextResponse.json({ active: true, since: sub.since });
      }
    }
  } catch {
    // fall through
  }

  return NextResponse.json({ active: false });
}
