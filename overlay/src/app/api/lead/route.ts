import { NextResponse } from "next/server";
import { getWorldCupPickOfDay, type WCPickOfDay } from "@/lib/wcData";

export const runtime = "nodejs";

/**
 * Free-list lead capture. Adds an email to the Resend Audience (the marketing
 * list we can later broadcast free plays to) and sends a welcome email.
 *
 * No database: Resend Audiences IS the store. Everything degrades gracefully —
 * if the API key or audience isn't configured yet, we log and still return ok
 * so the on-page UX never breaks. The only hard failure surfaced to the client
 * is an invalid email (so the form can show inline validation).
 */

const RESEND_API = "https://api.resend.com";

export async function POST(req: Request) {
  let email: string;
  let source = "site";
  let honeypot = "";
  try {
    const body = await req.json();
    email = String(body.email || "").trim().toLowerCase();
    if (body.source) source = String(body.source).slice(0, 60);
    honeypot = String(body.company || "").trim();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  // Honeypot: real users never fill a hidden "company" field; bots do. Pretend
  // success so the bot moves on without learning the field is a trap.
  if (honeypot) return NextResponse.json({ ok: true });

  if (!isValidEmail(email)) {
    return NextResponse.json({ error: "invalid_email" }, { status: 400 });
  }

  const apiKey = process.env.RESEND_API_KEY || process.env.EMAIL_SERVER_PASSWORD;
  const audienceId = process.env.RESEND_AUDIENCE_ID;
  const from = process.env.EMAIL_FROM || "Overlay <onboarding@resend.dev>";

  if (!apiKey) {
    console.error("lead: missing RESEND_API_KEY / EMAIL_SERVER_PASSWORD", { email, source });
    return NextResponse.json({ ok: true });
  }

  // 1) Add to the audience (the list). Resend treats a re-add of an existing
  //    contact as a 409/200 — either way the email ends up on the list, so we
  //    don't treat a non-2xx here as fatal to the user.
  if (audienceId) {
    try {
      const r = await fetch(`${RESEND_API}/audiences/${audienceId}/contacts`, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ email, unsubscribed: false }),
      });
      if (!r.ok && r.status !== 409) {
        console.error("lead: audience add failed", r.status, await safeText(r));
      }
    } catch (err) {
      console.error("lead: audience add error", err);
    }
  } else {
    console.warn("lead: RESEND_AUDIENCE_ID not set — captured but not stored in an audience", { email, source });
  }

  // 2) Welcome email — with today's World Cup pick of the day baked in so the
  //    signup delivers a real free play immediately, not just a link.
  let pick: WCPickOfDay | null = null;
  try {
    pick = await getWorldCupPickOfDay();
  } catch (err) {
    console.error("lead: pick-of-day lookup failed", err);
  }

  try {
    await fetch(`${RESEND_API}/emails`, {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from,
        to: email,
        subject: pick
          ? `Your free World Cup play: ${pick.selection} (${pick.match})`
          : "You're on the Overlay free list",
        html: welcomeHtml(pick),
        text: welcomeText(pick),
      }),
    });
  } catch (err) {
    console.error("lead: welcome email error", err);
  }

  return NextResponse.json({ ok: true });
}

function fmtPrice(p: number | null): string {
  if (p == null) return "";
  return p > 0 ? `+${p}` : `${p}`;
}

function pickLine(pick: WCPickOfDay): string {
  const price = fmtPrice(pick.price);
  const probPct = `${Math.round(pick.prob * 100)}%`;
  const sel = pick.selection === "Draw" ? "Draw" : `${pick.selection} to win`;
  return `${sel}${price ? ` (${price})` : ""} — model ${probPct}, edge +${pick.edgePp}pp`;
}

function isValidEmail(email: string): boolean {
  // Pragmatic check: one @, a dot in the domain, no whitespace, sane length.
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 254;
}

async function safeText(r: Response): Promise<string> {
  try {
    return await r.text();
  } catch {
    return "";
  }
}

function pickBlockHtml(pick: WCPickOfDay): string {
  const meta = [pick.city, pick.time].filter(Boolean).join(" · ");
  return `
    <div style="background:#0A0B0D; border:1px solid rgba(18,197,138,0.35); border-radius:8px; padding:18px 20px; margin:0 0 24px;">
      <div style="font-size:10px; letter-spacing:0.16em; color:#12C58A; font-weight:700; margin-bottom:10px;">⚽ WORLD CUP PICK OF THE DAY</div>
      <div style="font-size:16px; font-weight:700; color:#F2F4F8; margin-bottom:4px;">${pick.match}</div>
      ${meta ? `<div style="font-size:12px; color:#5A6171; margin-bottom:12px;">${meta}</div>` : `<div style="margin-bottom:12px;"></div>`}
      <div style="font-size:18px; font-weight:800; color:#12C58A;">${pick.selection === "Draw" ? "Draw" : `${pick.selection} to win`}${pick.price != null ? ` <span style="color:#F2F4F8;">${fmtPrice(pick.price)}</span>` : ""}</div>
      <div style="font-size:13px; color:#8A93A3; margin-top:8px;">
        Model ${Math.round(pick.prob * 100)}% &nbsp;·&nbsp; edge <span style="color:#12C58A; font-weight:700;">+${pick.edgePp}pp</span> over the market
      </div>
    </div>`;
}

function welcomeHtml(pick: WCPickOfDay | null): string {
  const base = (process.env.NEXT_PUBLIC_SITE_URL || "https://overlay-gray.vercel.app").replace(/\/$/, "");
  const intro = pick
    ? "You're on the free list — here's today's World Cup play, on the house. Same three-model engine behind our public record, no parlays, no hype."
    : "We'll send a sharp free play before the biggest slates — same three-model engine behind our public record, no parlays, no hype.";
  return `<!DOCTYPE html>
<html><body style="font-family: -apple-system, sans-serif; background:#0A0B0D; color:#F2F4F8; padding:32px;">
  <div style="max-width:480px; margin:0 auto; background:#0F1115; border:1px solid #2A2F3A; border-radius:8px; padding:32px;">
    <div style="font-size:14px; letter-spacing:0.16em; color:#12C58A; font-weight:700; margin-bottom:24px;">OVERLAY</div>
    <h1 style="font-size:22px; margin:0 0 12px; color:#F2F4F8;">You're on the free list.</h1>
    <p style="color:#8A93A3; line-height:1.6; margin:0 0 24px;">${intro}</p>
    ${pick ? pickBlockHtml(pick) : ""}
    <a href="${base}/world-cup" style="display:inline-block; background:#12C58A; color:white; padding:12px 22px; border-radius:4px; text-decoration:none; font-weight:700;">
      See the full World Cup model →
    </a>
    <p style="color:#8A93A3; line-height:1.6; margin:20px 0 0; font-size:13px;">
      Ready for the daily NBA &amp; MLB card? <a href="${base}/#pricing" style="color:#12C58A; text-decoration:none;">Lock in founding access</a>.
    </p>
    <p style="color:#5A6171; font-size:12px; margin-top:24px;">
      You got this because you signed up at overlay. Not for you? Just reply "stop" and you're off the list.
    </p>
  </div>
</body></html>`;
}

function welcomeText(pick: WCPickOfDay | null): string {
  const base = (process.env.NEXT_PUBLIC_SITE_URL || "https://overlay-gray.vercel.app").replace(/\/$/, "");
  const lines = ["You're on the Overlay free list.", ""];
  if (pick) {
    lines.push(
      "WORLD CUP PICK OF THE DAY",
      `${pick.match}${pick.city ? ` — ${pick.city}` : ""}`,
      pickLine(pick),
      "",
    );
  } else {
    lines.push(
      "We'll send a sharp free play before the biggest slates — same three-model engine behind our public record. No parlays, no hype.",
      "",
    );
  }
  lines.push(
    `Full World Cup model: ${base}/world-cup`,
    `Founding access to the daily card: ${base}/#pricing`,
    "",
    'Not for you? Reply "stop" and you\'re off the list.',
  );
  return lines.join("\n");
}
