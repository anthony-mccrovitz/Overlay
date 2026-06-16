import { getSession, isAllowlisted } from "@/lib/session";
import { SlateClient } from "@/components/slate/SlateClient";

export const dynamic = "force-dynamic";

export default function SlatePage() {
  // Determine Pro status server-side (no auth wall — anyone can view, just Pro unlocks ML probs)
  let isPro = false;
  try {
    const session = getSession();
    isPro = !!(session?.email && isAllowlisted(session.email));
  } catch {
    isPro = false;
  }

  return <SlateClient isPro={isPro} />;
}
