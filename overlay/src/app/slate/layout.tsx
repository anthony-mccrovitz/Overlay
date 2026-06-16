import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Today's Full Model Slate — MLB, NBA, NHL Picks",
  description:
    "Every game evaluated by the Overlay ensemble model today. Edge %, model probability vs market implied, positive EV highlighted. MLB totals, NRFI, F5, NBA totals — free to view.",
  keywords: [
    "MLB picks today",
    "NBA picks today",
    "MLB totals model picks",
    "positive EV sports betting",
    "sports betting model slate",
    "NRFI picks today",
    "MLB edge picks",
    "sports betting edge detection",
    "MLB model predictions",
    "NBA model predictions",
  ],
  openGraph: {
    title: "Today's Full Model Slate",
    description: "Every game the ML ensemble evaluated — edge %, model vs market implied, card picks. Free.",
    type: "website",
  },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
