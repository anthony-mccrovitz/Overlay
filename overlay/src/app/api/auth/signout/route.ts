import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE_NAME, siteUrl } from "@/lib/session";

export const runtime = "nodejs";

export async function POST() {
  cookies().delete(SESSION_COOKIE_NAME);
  return NextResponse.redirect(`${siteUrl()}/`);
}

export async function GET() {
  cookies().delete(SESSION_COOKIE_NAME);
  return NextResponse.redirect(`${siteUrl()}/`);
}
