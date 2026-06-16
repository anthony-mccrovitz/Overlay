import { NextResponse } from "next/server";
import { isAllowlisted, magicToken, siteUrl } from "@/lib/session";

export const runtime = "nodejs";

export async function POST(req: Request) {
  let email: string;
  try {
    const body = await req.json();
    email = String(body.email || "").trim().toLowerCase();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  if (!email || !email.includes("@")) {
    return NextResponse.json({ error: "invalid_email" }, { status: 400 });
  }

  // Don't tell the world whether an email is on the allowlist. Always respond
  // 200 so unauthorized addresses can't enumerate subscribers.
  if (!isAllowlisted(email)) {
    return NextResponse.json({ ok: true });
  }

  const token = magicToken(email);
  const link = `${siteUrl()}/api/auth/verify?token=${encodeURIComponent(token)}`;

  const apiKey = process.env.RESEND_API_KEY || process.env.EMAIL_SERVER_PASSWORD;
  const from = process.env.EMAIL_FROM || "Overlay <onboarding@resend.dev>";
  if (!apiKey) {
    console.error("Missing RESEND_API_KEY / EMAIL_SERVER_PASSWORD");
    return NextResponse.json({ ok: true });
  }

  try {
    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from,
        to: email,
        subject: "Sign in to Overlay",
        html: signInHtml(link),
        text: `Sign in to Overlay: ${link}\n\nThis link expires in 15 minutes.`,
      }),
    });
    if (!r.ok) {
      const body = await r.text();
      console.error("Resend error:", r.status, body);
    }
  } catch (err) {
    console.error("Resend fetch failed:", err);
  }

  return NextResponse.json({ ok: true });
}

function signInHtml(link: string): string {
  return `<!DOCTYPE html>
<html><body style="font-family: -apple-system, sans-serif; background:#0A0B0D; color:#F2F4F8; padding:32px;">
  <div style="max-width:480px; margin:0 auto; background:#0F1115; border:1px solid #2A2F3A; border-radius:8px; padding:32px;">
    <div style="font-size:14px; letter-spacing:0.16em; color:#12C58A; font-weight:700; margin-bottom:24px;">OVERLAY</div>
    <h1 style="font-size:22px; margin:0 0 12px; color:#F2F4F8;">Sign in to your account</h1>
    <p style="color:#8A93A3; line-height:1.6; margin:0 0 24px;">
      Click the button below to access your subscriber dashboard. This link expires in 15 minutes.
    </p>
    <a href="${link}" style="display:inline-block; background:#12C58A; color:white; padding:12px 22px; border-radius:4px; text-decoration:none; font-weight:700;">
      Sign in to Overlay
    </a>
    <p style="color:#5A6171; font-size:12px; margin-top:24px;">
      If you didn't request this, you can ignore this email.
    </p>
  </div>
</body></html>`;
}
