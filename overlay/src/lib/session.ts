/**
 * Custom stateless magic-link auth.
 *
 * No database, no NextAuth, no adapter. A signed token in a cookie is the
 * whole session. The token = `base64(payload).hmac` — verifying it doesn't
 * require any server-side storage, so this works on Vercel's edge/serverless
 * model out of the box.
 */

import crypto from "crypto";
import { cookies } from "next/headers";

const COOKIE_NAME = "overlay_session";
const SESSION_TTL_DAYS = 30;
const MAGIC_LINK_TTL_MINUTES = 15;

function secret(): string {
  const s = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET;
  if (!s) throw new Error("AUTH_SECRET (or NEXTAUTH_SECRET) is required");
  return s;
}

function b64urlEncode(buf: Buffer | string): string {
  return Buffer.from(buf).toString("base64url");
}

function b64urlDecode(s: string): Buffer {
  return Buffer.from(s, "base64url");
}

export type TokenPayload = { email: string; exp: number; purpose: "magic" | "session" };

export function signToken(payload: TokenPayload): string {
  const data = b64urlEncode(JSON.stringify(payload));
  const sig = crypto.createHmac("sha256", secret()).update(data).digest("base64url");
  return `${data}.${sig}`;
}

export function verifyToken(token: string | undefined | null): TokenPayload | null {
  if (!token) return null;
  const [data, sig] = token.split(".");
  if (!data || !sig) return null;
  let expected: string;
  try {
    expected = crypto.createHmac("sha256", secret()).update(data).digest("base64url");
  } catch {
    return null;
  }
  if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return null;
  try {
    const payload = JSON.parse(b64urlDecode(data).toString()) as TokenPayload;
    if (payload.exp < Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}

export function magicToken(email: string): string {
  return signToken({
    email: email.toLowerCase(),
    exp: Date.now() + MAGIC_LINK_TTL_MINUTES * 60_000,
    purpose: "magic",
  });
}

export function sessionToken(email: string): string {
  return signToken({
    email: email.toLowerCase(),
    exp: Date.now() + SESSION_TTL_DAYS * 24 * 60 * 60 * 1000,
    purpose: "session",
  });
}

export function isAllowlisted(email: string): boolean {
  const list = (process.env.PAID_EMAILS || "")
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
  return list.includes(email.toLowerCase());
}

/** Read the current session from the cookie (server components / route handlers). */
export function getSession(): { email: string } | null {
  try {
    const c = cookies().get(COOKIE_NAME);
    const payload = verifyToken(c?.value);
    if (!payload || payload.purpose !== "session") return null;
    return { email: payload.email };
  } catch {
    return null;
  }
}

export const SESSION_COOKIE_NAME = COOKIE_NAME;
export const SESSION_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
  maxAge: SESSION_TTL_DAYS * 24 * 60 * 60,
};

export function siteUrl(): string {
  const url = process.env.SITE_URL || process.env.NEXTAUTH_URL;
  if (url) return url.replace(/\/$/, "");
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  return "http://localhost:3002";
}
