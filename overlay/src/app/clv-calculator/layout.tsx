import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "CLV Calculator — Closing Line Value",
  description:
    "Free closing line value (CLV) calculator. Paste the odds you got and the closing line to instantly see your CLV%, whether you beat the book, and what it means for your long-run edge.",
  keywords: [
    "closing line value calculator",
    "CLV calculator",
    "CLV betting",
    "closing line value",
    "beat the close",
    "betting edge calculator",
    "sharp betting calculator",
    "CLV sports betting",
    "did i get good odds",
    "sports betting skill calculator",
  ],
  openGraph: {
    title: "CLV Calculator — Did You Beat the Close?",
    description: "Closing line value is the best predictor of long-run betting profitability. Free tool, no login.",
    type: "website",
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is closing line value (CLV) in sports betting?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Closing Line Value (CLV) is the difference between the odds you got when you placed a bet and the final closing odds on the same market. Positive CLV means you got a better price than where the market settled — indicating you were on the right side of sharp money. CLV is widely considered the best short-term predictor of long-run betting profitability.",
      },
    },
    {
      "@type": "Question",
      name: "How do you calculate closing line value?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Convert your bet odds and the closing odds to no-vig implied probabilities. CLV = your no-vig implied probability minus the no-vig closing implied probability for the same side. A positive number means you beat the close; negative means the market moved against you after you bet.",
      },
    },
    {
      "@type": "Question",
      name: "What is a good CLV in sports betting?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "A sustained average CLV of +2 to +3 percentage points or higher is considered sharp. Even +1pp average CLV over hundreds of bets is meaningful edge. Negative average CLV (consistently getting worse odds than close) strongly predicts long-run losses regardless of short-term W/L record.",
      },
    },
    {
      "@type": "Question",
      name: "Why is CLV better than win rate for evaluating betting skill?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Win rate over small samples is mostly luck. CLV measures whether you're consistently getting better prices than the market's final assessment, which requires genuine information advantage or timing skill. Pinnacle and other sharp books use CLV to identify winning bettors and limit their accounts — making it the most reliable skill signal available.",
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
