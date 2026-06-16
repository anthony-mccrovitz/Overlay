import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "No-Vig Fair Odds Calculator",
  description:
    "Free no-vig odds calculator. Paste any two-sided or three-way betting market to instantly find the true fair odds and the exact vig (hold) percentage you're paying.",
  keywords: [
    "no vig calculator",
    "fair odds calculator",
    "hold calculator",
    "betting vig calculator",
    "juice calculator",
    "implied probability calculator",
    "no juice odds",
    "sports betting calculator",
    "remove vig from odds",
    "sportsbook margin calculator",
  ],
  openGraph: {
    title: "No-Vig Fair Odds Calculator — Free Tool",
    description: "Strip the sportsbook margin and find the true fair odds. Instant, free, no login.",
    type: "website",
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is a no-vig calculator?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "A no-vig calculator strips the sportsbook's built-in margin (the 'vig' or 'juice') from a betting market to reveal the true implied probability and fair odds for each side. For a standard -110/-110 market, the no-vig fair odds are approximately -100/-100, and the hold is 4.76%.",
      },
    },
    {
      "@type": "Question",
      name: "How do you calculate no-vig odds?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Convert each side's American odds to implied probability. Sum the implied probabilities (the total will exceed 100% — the excess is the vig). Divide each side's implied probability by the total to normalize to 100%. Convert the normalized probabilities back to American odds. Those are the no-vig fair odds.",
      },
    },
    {
      "@type": "Question",
      name: "What is a good hold percentage for a sportsbook?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Pinnacle (the sharpest book) runs a hold of 2-3%. Retail books like DraftKings and FanDuel typically hold 4.5-8%. Above 8% is considered high-juice and disadvantageous for the bettor. The hold percentage is what the book keeps, on average, from every dollar wagered.",
      },
    },
    {
      "@type": "Question",
      name: "What is the difference between vig and hold?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Hold is the total implied probability minus 100% — the raw overround. Vig is the percentage of total action the book keeps (hold divided by total implied). For a -110/-110 market: total implied = 52.4% + 52.4% = 104.8%, so hold = 4.8% and vig = 4.8%/104.8% = 4.58%.",
      },
    },
  ],
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      {children}
    </>
  );
}
