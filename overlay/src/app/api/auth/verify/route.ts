import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  SESSION_COOKIE_NAME,
  SESSION_COOKIE_OPTIONS,
  isAllowlisted,
  sessionToken,
  siteUrl,
  verifyToken,
} from "@/lib/session";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const token = url.searchParams.get("token");
  const payload = verifyToken(token);
  if (!payload || payload.purpose !== "magic") {
    return NextResponse.redirect(`${siteUrl()}/login?error=invalid`);
  }
  if (!isAllowlisted(payload.email)) {
    return NextResponse.redirect(`${siteUrl()}/login?error=not_subscribed`);
  }

  cookies().set(SESSION_COOKIE_NAME, sessionToken(payload.email), SESSION_COOKIE_OPTIONS);
  return NextResponse.redirect(`${siteUrl()}/picks`);
}
