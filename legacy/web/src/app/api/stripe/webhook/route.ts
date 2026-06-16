import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { readFileSync, writeFileSync, existsSync } from "fs";
import { join } from "path";

function getStripe() {
  return new Stripe(process.env.STRIPE_SECRET_KEY!, {
    apiVersion: "2026-03-25.dahlia",
  });
}

// Write subscriber emails to a JSON file in the repo.
// MVP: no database, no auth system. Just email → subscription status.
// Works fine until ~20 subscribers at which point you should add a real DB.
const SUBSCRIBERS_FILE = join(process.cwd(), "..", "data", "subscribers.json");

function loadSubscribers(): Record<string, { email: string; since: string; active: boolean }> {
  try {
    if (existsSync(SUBSCRIBERS_FILE)) {
      return JSON.parse(readFileSync(SUBSCRIBERS_FILE, "utf-8"));
    }
  } catch {
    // fall through
  }
  return {};
}

function saveSubscribers(subs: Record<string, { email: string; since: string; active: boolean }>) {
  try {
    writeFileSync(SUBSCRIBERS_FILE, JSON.stringify(subs, null, 2));
  } catch (err) {
    console.error("Failed to save subscribers:", err);
  }
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  const sig = req.headers.get("stripe-signature");

  if (!sig || !process.env.STRIPE_WEBHOOK_SECRET) {
    return NextResponse.json({ error: "Missing signature" }, { status: 400 });
  }

  let event: Stripe.Event;
  try {
    event = getStripe().webhooks.constructEvent(body, sig, process.env.STRIPE_WEBHOOK_SECRET);
  } catch (err) {
    console.error("Webhook signature verification failed:", err);
    return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    const email = session.customer_email || session.customer_details?.email;

    if (email) {
      const subs = loadSubscribers();
      subs[email] = {
        email,
        since: new Date().toISOString(),
        active: true,
      };
      saveSubscribers(subs);
      console.log(`[webhook] New subscriber: ${email}`);
    }
  }

  if (event.type === "customer.subscription.deleted") {
    const sub = event.data.object as Stripe.Subscription;
    // Find by customer ID — requires looking up customer email
    try {
      const customer = await getStripe().customers.retrieve(sub.customer as string) as Stripe.Customer;
      const email = customer.email;
      if (email) {
        const subs = loadSubscribers();
        if (subs[email]) {
          subs[email].active = false;
          saveSubscribers(subs);
          console.log(`[webhook] Subscription cancelled: ${email}`);
        }
      }
    } catch {
      // Non-fatal — subscriber stays active if lookup fails
    }
  }

  return NextResponse.json({ received: true });
}
