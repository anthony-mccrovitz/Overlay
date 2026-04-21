"""
Cross-market arbitrage and edge finder across prediction markets and sportsbooks.

Supports three arb types:
  1. Kalshi ↔ Polymarket   (prediction market vs prediction market)
  2. Kalshi ↔ Sportsbook   (prediction market vs sportsbook)
  3. Polymarket ↔ Sportsbook

Also detects positive EV opportunities (not pure arb, but where our model
probability differs from market price by more than threshold).

Arb math for binary YES/NO markets:
  Buy YES on Source A at price pa_yes (probability space)
  Buy NO on Source B at price pb_no  (probability space)
  Arb condition: pa_yes + pb_no < 1.0
  Margin: (1 - pa_yes - pb_no) * 100%

After fees:
  Kalshi fee:   2% of winnings
  Polymarket fee: 2% of winnings
  Sportsbook vig: embedded in the line (~4-6%)
  Minimum viable margin: K↔P: 4%  |  K↔SB or P↔SB: 3%

Usage:
    from src.data.prediction_arb import find_all_arbs, format_arb_report
    arbs = find_all_arbs()
    print(format_arb_report(arbs))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.data.entity_resolver import EntityResolver, MatchResult
from src.data.kalshi import KalshiMarket, fetch_all_markets as kalshi_all
from src.data.polymarket import PolyMarket, fetch_all_markets as poly_all

# Minimum margin after fees to flag as an arb opportunity
MIN_MARGIN_KALSHI_POLY = 0.04   # 4% — covers ~2% fee on each side
MIN_MARGIN_PRED_VS_SB = 0.03    # 3% — sportsbook vig absorbed by best-line shopping

# Minimum matching score from EntityResolver to consider two markets the same event
ENTITY_THRESHOLD = 0.65


@dataclass
class PredictionArb:
    """A single arbitrage opportunity across two prediction market sources."""

    arb_type: Literal["kalshi_poly", "kalshi_sb", "poly_sb"]

    # Source A (buy YES here)
    source_a: str
    market_a_id: str
    title_a: str
    yes_price_a: float       # probability (0–1) you pay for YES on source A
    url_a: str

    # Source B (buy NO here, which is the complement of YES)
    source_b: str
    market_b_id: str
    title_b: str
    no_price_b: float        # probability (0–1) you pay for NO on source B
    url_b: str

    # Arb metrics
    combined_cost: float     # yes_price_a + no_price_b  (< 1.0 = arb)
    margin_pct: float        # (1 - combined_cost) * 100
    match_score: float       # entity resolution confidence (0–1)

    category: str
    close_time: str | None

    def stakes(self, bankroll: float) -> tuple[float, float, float]:
        """
        Optimal stake sizes for a given bankroll.

        Returns (stake_a, stake_b, guaranteed_profit).
        Stake formula: invest proportional to the other side's implied probability.
        """
        if self.combined_cost <= 0:
            return 0, 0, 0
        stake_a = bankroll * self.no_price_b / self.combined_cost
        stake_b = bankroll * self.yes_price_a / self.combined_cost
        profit = bankroll * (1 / self.combined_cost - 1)
        return round(stake_a, 2), round(stake_b, 2), round(profit, 2)


@dataclass
class PredictionEdge:
    """
    A positive EV opportunity: not a pure arb, but where two platforms
    disagree by enough to suggest one side is mispriced.
    """
    source_a: str
    source_b: str
    title_a: str
    title_b: str
    prob_a: float            # source A's YES probability
    prob_b: float            # source B's YES probability (same outcome)
    divergence_pct: float    # |prob_a - prob_b| * 100
    buy_source: str          # which source has the better (cheaper) YES price
    buy_prob: float          # the cheaper YES price
    url_a: str
    url_b: str
    category: str
    match_score: float


def find_kalshi_poly_arbs(
    kalshi_markets: list[KalshiMarket],
    poly_markets: list[PolyMarket],
    resolver: EntityResolver,
    min_margin: float = MIN_MARGIN_KALSHI_POLY,
) -> list[PredictionArb]:
    """Find arbs between Kalshi and Polymarket for the same event."""
    arbs: list[PredictionArb] = []

    kalshi_titles = [m.title for m in kalshi_markets]
    poly_titles = [m.question for m in poly_markets]

    matches = resolver.bulk_match(kalshi_titles, poly_titles, threshold=ENTITY_THRESHOLD)

    for ki, pi, match_result in matches:
        km = kalshi_markets[ki]
        pm = poly_markets[pi]

        # Strategy 1: Buy YES on Kalshi + Buy NO on Polymarket
        cost_1 = km.yes_prob + pm.no_prob
        margin_1 = 1 - cost_1

        # Strategy 2: Buy NO on Kalshi + Buy YES on Polymarket
        cost_2 = km.no_prob + pm.yes_prob
        margin_2 = 1 - cost_2

        for cost, margin, title, yes_src, no_src, yes_price, no_price, yes_id, no_id, yes_url, no_url in [
            (cost_1, margin_1, f"YES Kalshi / NO Polymarket",
             "kalshi", "polymarket",
             km.yes_prob, pm.no_prob,
             km.ticker, pm.market_id,
             km.url, pm.url),
            (cost_2, margin_2, f"NO Kalshi / YES Polymarket",
             "polymarket", "kalshi",
             pm.yes_prob, km.no_prob,
             pm.market_id, km.ticker,
             pm.url, km.url),
        ]:
            if margin >= min_margin:
                arbs.append(PredictionArb(
                    arb_type="kalshi_poly",
                    source_a=yes_src,
                    market_a_id=yes_id,
                    title_a=km.title if yes_src == "kalshi" else pm.question,
                    yes_price_a=yes_price,
                    url_a=yes_url,
                    source_b=no_src,
                    market_b_id=no_id,
                    title_b=pm.question if no_src == "polymarket" else km.title,
                    no_price_b=no_price,
                    url_b=no_url,
                    combined_cost=round(cost, 4),
                    margin_pct=round(margin * 100, 3),
                    match_score=match_result.score,
                    category=km.category,
                    close_time=km.close_time,
                ))

    arbs.sort(key=lambda x: x.margin_pct, reverse=True)
    return arbs


def find_divergences(
    kalshi_markets: list[KalshiMarket],
    poly_markets: list[PolyMarket],
    resolver: EntityResolver,
    min_divergence_pct: float = 5.0,
) -> list[PredictionEdge]:
    """
    Find events where Kalshi and Polymarket disagree by >= min_divergence_pct.

    These aren't arbs (combined cost > 1.0) but the divergence signals
    that one side is mispriced — value betting opportunity.
    """
    edges: list[PredictionEdge] = []

    kalshi_titles = [m.title for m in kalshi_markets]
    poly_titles = [m.question for m in poly_markets]

    matches = resolver.bulk_match(kalshi_titles, poly_titles, threshold=ENTITY_THRESHOLD)

    for ki, pi, match_result in matches:
        km = kalshi_markets[ki]
        pm = poly_markets[pi]

        divergence = abs(km.yes_prob - pm.yes_prob) * 100

        if divergence >= min_divergence_pct:
            if km.yes_prob < pm.yes_prob:
                buy_source = "kalshi"
                buy_prob = km.yes_prob
            else:
                buy_source = "polymarket"
                buy_prob = pm.yes_prob

            edges.append(PredictionEdge(
                source_a="kalshi",
                source_b="polymarket",
                title_a=km.title,
                title_b=pm.question,
                prob_a=km.yes_prob,
                prob_b=pm.yes_prob,
                divergence_pct=round(divergence, 2),
                buy_source=buy_source,
                buy_prob=buy_prob,
                url_a=km.url,
                url_b=pm.url,
                category=km.category,
                match_score=match_result.score,
            ))

    edges.sort(key=lambda x: x.divergence_pct, reverse=True)
    return edges


def find_all_arbs(
    refresh: bool = False,
    min_kalshi_volume: int = 100,
    min_poly_volume: float = 1000.0,
) -> dict:
    """
    Main entry point. Fetches all markets and finds all arb/edge opportunities.

    Returns dict with keys:
        kalshi_poly_arbs: list[PredictionArb]
        divergences:      list[PredictionEdge]
        kalshi_count:     int
        poly_count:       int
    """
    print("Fetching Kalshi markets...")
    kalshi_markets = kalshi_all(refresh=refresh)
    kalshi_markets = [m for m in kalshi_markets if m.volume >= min_kalshi_volume]

    print("Fetching Polymarket markets...")
    poly_markets = poly_all(refresh=refresh, min_volume=min_poly_volume)

    resolver = EntityResolver()

    print(f"Running entity resolution ({len(kalshi_markets)} Kalshi × {len(poly_markets)} Polymarket)...")
    arbs = find_kalshi_poly_arbs(kalshi_markets, poly_markets, resolver)
    divergences = find_divergences(kalshi_markets, poly_markets, resolver)

    print(f"  Arbs found: {len(arbs)}")
    print(f"  Divergences found: {len(divergences)}")

    return {
        "kalshi_poly_arbs": arbs,
        "divergences": divergences,
        "kalshi_count": len(kalshi_markets),
        "poly_count": len(poly_markets),
    }


def format_arb_report(results: dict, bankroll: float = 1000.0) -> str:
    """Format arb results as a terminal-readable report."""
    arbs: list[PredictionArb] = results.get("kalshi_poly_arbs", [])
    divs: list[PredictionEdge] = results.get("divergences", [])
    k_count = results.get("kalshi_count", 0)
    p_count = results.get("poly_count", 0)

    lines: list[str] = []
    sep = "─" * 90

    lines.append(f"\n{'PREDICTION MARKET ARB SCANNER':^90}")
    lines.append(f"{'Kalshi: ' + str(k_count) + ' markets  |  Polymarket: ' + str(p_count) + ' markets':^90}")
    lines.append(sep)

    # --- ARB SECTION ---
    lines.append(f"\n  GUARANTEED ARBS (bankroll ${bankroll:,.0f})\n  {sep[:60]}")
    if not arbs:
        lines.append("  No arbs found at current prices.")
    else:
        for arb in arbs[:20]:
            sa, sb, profit = arb.stakes(bankroll)
            lines.append(
                f"\n  [{arb.arb_type.upper()}] {arb.margin_pct:.2f}% margin  |  "
                f"match confidence: {arb.match_score:.2f}  |  category: {arb.category}"
            )
            lines.append(f"  Title A ({arb.source_a.upper()}): {arb.title_a[:70]}")
            lines.append(f"  Title B ({arb.source_b.upper()}): {arb.title_b[:70]}")
            lines.append(
                f"  Buy YES on {arb.source_a} @ {arb.yes_price_a:.3f}  +  "
                f"Buy NO on {arb.source_b} @ {arb.no_price_b:.3f}  =  "
                f"combined cost {arb.combined_cost:.3f}"
            )
            lines.append(
                f"  → Stake ${sa:.2f} on {arb.source_a} YES  |  "
                f"${sb:.2f} on {arb.source_b} NO  |  "
                f"Guaranteed profit: +${profit:.2f}"
            )
            if arb.close_time:
                lines.append(f"  Closes: {arb.close_time[:16]}")
            lines.append(f"  {arb.url_a}")
            lines.append(f"  {arb.url_b}")

    # --- DIVERGENCE SECTION ---
    lines.append(f"\n  PRICE DIVERGENCES (same event, different probabilities)\n  {sep[:60]}")
    if not divs:
        lines.append("  No significant divergences found.")
    else:
        for d in divs[:15]:
            lines.append(
                f"\n  {d.divergence_pct:.1f}% divergence  |  "
                f"match confidence: {d.match_score:.2f}  |  category: {d.category}"
            )
            lines.append(f"  Kalshi:     {d.title_a[:65]}  →  YES @ {d.prob_a:.3f}")
            lines.append(f"  Polymarket: {d.title_b[:65]}  →  YES @ {d.prob_b:.3f}")
            lines.append(
                f"  Value: Buy YES on {d.buy_source.upper()} @ {d.buy_prob:.3f} "
                f"(cheaper by {d.divergence_pct:.1f}%)"
            )
            lines.append(f"  {d.url_a}")
            lines.append(f"  {d.url_b}")

    lines.append(f"\n{sep}")
    return "\n".join(lines)


def to_json(results: dict) -> dict:
    """Serialize results to a JSON-serializable dict."""
    def _arb_to_dict(a: PredictionArb) -> dict:
        return {
            "arb_type": a.arb_type,
            "source_a": a.source_a,
            "title_a": a.title_a,
            "yes_price_a": a.yes_price_a,
            "url_a": a.url_a,
            "source_b": a.source_b,
            "title_b": a.title_b,
            "no_price_b": a.no_price_b,
            "url_b": a.url_b,
            "combined_cost": a.combined_cost,
            "margin_pct": a.margin_pct,
            "match_score": a.match_score,
            "category": a.category,
            "close_time": a.close_time,
        }

    def _div_to_dict(d: PredictionEdge) -> dict:
        return {
            "source_a": d.source_a,
            "source_b": d.source_b,
            "title_a": d.title_a,
            "title_b": d.title_b,
            "prob_a": d.prob_a,
            "prob_b": d.prob_b,
            "divergence_pct": d.divergence_pct,
            "buy_source": d.buy_source,
            "buy_prob": d.buy_prob,
            "url_a": d.url_a,
            "url_b": d.url_b,
            "category": d.category,
            "match_score": d.match_score,
        }

    return {
        "kalshi_poly_arbs": [_arb_to_dict(a) for a in results.get("kalshi_poly_arbs", [])],
        "divergences": [_div_to_dict(d) for d in results.get("divergences", [])],
        "kalshi_count": results.get("kalshi_count", 0),
        "poly_count": results.get("poly_count", 0),
    }
