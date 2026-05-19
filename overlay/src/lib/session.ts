import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";

/**
 * Safe wrapper around getServerSession.
 *
 * NextAuth requires NEXTAUTH_SECRET in production — without it, getServerSession
 * throws and every gated route crashes with "Application error". This wrapper
 * swallows the throw and returns null, so gated pages fall back to the
 * "please sign in" state instead of 500-ing.
 */
export async function safeSession() {
  if (!process.env.NEXTAUTH_SECRET) return null;
  try {
    return await getServerSession(authOptions);
  } catch {
    return null;
  }
}
