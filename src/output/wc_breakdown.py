"""World Cup full-market breakdown — every market's model lean per game.

The daily pipeline only LOGS edges that clear the bet threshold (≥4%), so the
saved WC output showed moneyline-only on days the model didn't like a total or
spread enough to bet. This builds the COMPLETE picture instead: for every game,
the best available price (and the model's edge) on moneyline / total / spread /
anytime-scorer — including sub-threshold leans — so you can see what the model
thinks across the whole board, not just what it would bet.

build_breakdown() dedups a flat edge list (every book × every outcome) down to
the best price per selection; render() formats it as a readable table. The
pipeline writes both breakdown.json (structured) and breakdown.txt (readable)
into the day's WC output dir.
"""
from __future__ import annotations

from collections import defaultdict


def _odds_str(o) -> str:
    try:
        return f"{int(o):+d}"
    except (ValueError, TypeError):
        return str(o)


def _norm_market(mk: str) -> str:
    if mk in ("anytime_scorer", "player_goal_scorer_anytime", "scorer"):
        return "scorer"
    return mk or "?"


def _sel_key(e: dict) -> tuple:
    """A selection's identity within a game+market (so best price wins per pick)."""
    mk = _norm_market(e.get("market", "?"))
    if mk == "moneyline":
        return (mk, e.get("team") or e.get("direction"))
    if mk == "total":
        return (mk, e.get("direction"), e.get("line"))
    if mk == "spread":
        return (mk, e.get("team"), e.get("line"))
    if mk == "scorer":
        return (mk, e.get("player") or e.get("team"))
    return (mk, str(e.get("team")), str(e.get("direction")), str(e.get("line")))


def build_breakdown(edges: list[dict]) -> dict:
    """Group a flat edge list into {matchup: {market: [best-price selections]}}.

    Keeps the single best-priced row per (game, market, selection) — since the
    model edge rises with price, max edge == best number. Selections within a
    market are sorted by edge desc.
    """
    best: dict = {}
    for e in edges:
        mu = e.get("matchup", "?")
        key = (mu,) + _sel_key(e)
        cur = best.get(key)
        if cur is None or (e.get("edge_pct") or -999) > (cur.get("edge_pct") or -999):
            best[key] = e

    games: dict = defaultdict(lambda: defaultdict(list))
    for e in best.values():
        games[e.get("matchup", "?")][_norm_market(e.get("market", "?"))].append(e)
    # sort selections within each market by edge desc
    out: dict = {}
    for mu, markets in games.items():
        out[mu] = {}
        for mk, rows in markets.items():
            rows.sort(key=lambda r: -(r.get("edge_pct") or -999))
            out[mu][mk] = rows
    return out


_MARKET_ORDER = ["moneyline", "total", "spread", "scorer"]
_MARKET_LABEL = {"moneyline": "MONEYLINE (1X2)", "total": "TOTALS (goals)",
                 "spread": "ASIAN HANDICAP", "scorer": "ANYTIME SCORER"}


def _label(e: dict) -> str:
    mk = _norm_market(e.get("market", "?"))
    if mk == "total":
        return f"{e.get('direction')} {e.get('line')}"
    if mk == "spread":
        ln = e.get("line")
        ln_s = f"{ln:+g}" if isinstance(ln, (int, float)) else str(ln)
        return f"{e.get('team')} {ln_s}"
    if mk == "scorer":
        return str(e.get("player") or e.get("team") or "")
    return str(e.get("team") or e.get("direction") or "")


def render(breakdown: dict, date_str: str = "", max_scorers: int = 6) -> str:
    """Readable per-game, per-market table. Selections show best book/odds, the
    model prob vs market prob, and the edge."""
    lines: list[str] = []
    hdr = f"  WORLD CUP — full market breakdown" + (f" ({date_str})" if date_str else "")
    lines.append(hdr)
    lines.append("  " + "─" * 78)
    if not breakdown:
        lines.append("  (no games)")
        return "\n".join(lines)
    for mu in sorted(breakdown):
        lines.append(f"\n  ▌{mu}")
        markets = breakdown[mu]
        for mk in _MARKET_ORDER:
            rows = markets.get(mk)
            if not rows:
                continue
            shown = rows[:max_scorers] if mk == "scorer" else rows
            lines.append(f"    {_MARKET_LABEL.get(mk, mk.upper())}:")
            for e in shown:
                mp, ip = e.get("model_prob"), e.get("implied_prob")
                mp_s = f"{mp*100:4.1f}%" if mp is not None else "  -  "
                ip_s = f"{ip*100:4.1f}%" if ip is not None else "  -  "
                lines.append(
                    f"      {_label(e)[:26]:26} {_odds_str(e.get('odds')):>6} "
                    f"{str(e.get('sportsbook') or '')[:12]:12}  "
                    f"model {mp_s} vs mkt {ip_s}  edge {e.get('edge_pct', 0):+5.1f}%")
    lines.append("\n  edge = model prob − market (de-vigged) prob. WC is a SHADOW model —")
    lines.append("  totals/handicap edges run hot (overconfident); treat as leans, not locks.")
    return "\n".join(lines)
