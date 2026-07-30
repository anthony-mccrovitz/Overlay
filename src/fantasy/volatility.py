"""Ceiling and floor: which players actually move a league table.

WHY THIS EXISTS. The draft board ranked on VORP alone, which is an EXPECTATION.
Two players with identical projections are not interchangeable: one grinds out
14 points every week, the other posts 4 and 31. Same mean, completely different
effect on a season.

Which you want depends on where you are. Frontier Economics' data scientists
found that clustering players by points VOLATILITY and deliberately drafting the
high-variance ones ("mavericks") is the fastest way to climb a table — because
you cannot catch the leader by matching them, only by out-scoring them. The
mirror holds too: if you are ahead, the low-variance player protects the lead.

WHAT WE CAN AND CANNOT MEASURE. We do not carry week-by-week game logs, so this
does not compute realised weekly standard deviation. It estimates volatility
from the structural drivers we DO have, each of which is a known variance source
rather than a guess:

  position    RB/TE outcomes are famously touchdown-dependent and lumpier than
              the target-volume floor a WR or QB sits on
  depth       a clear starter has a stable role; a committee back's usage swings
              week to week on game script
  games_2025  a short sample is itself uncertainty — the projection is thinner
  age         past the curve, decline arrives unevenly rather than smoothly
  injury      a flagged player carries a bimodal outcome, not a wider one

That is an ESTIMATE built from priors, not a measurement, and it is labelled as
such everywhere it surfaces. It is meant to break ties between similar VORPs and
to say which way a pick is wrong, not to reorder the board.
"""
from __future__ import annotations

from dataclasses import dataclass

# Baseline weekly volatility by position, as a share of that player's mean.
# RB and TE lean on touchdowns, which arrive in clumps; QB and WR sit on volume
# that shows up most weeks. These are priors from how the positions score, not
# fitted values — a fitted version needs weekly game logs we do not store.
_POS_BASE: dict[str, float] = {
    "QB": 0.28,
    "WR": 0.34,
    "RB": 0.42,
    "TE": 0.46,
    "K": 0.50,
    "DEF": 0.55,
}
_DEFAULT_BASE = 0.38


@dataclass(frozen=True)
class Volatility:
    sigma_pct: float      # estimated weekly spread, share of the mean
    ceiling: float        # ~90th-percentile season outcome
    floor: float          # ~10th-percentile season outcome
    label: str            # STEADY | BALANCED | SWINGY
    drivers: str          # what pushed it, in plain words

    @property
    def is_maverick(self) -> bool:
        """High variance — the shape you want when chasing, not protecting."""
        return self.label == "SWINGY"


def estimate(position: str, proj_points: float, *, depth: int | None = None,
             games_2025: float | None = None, age_factor: float = 1.0,
             note: str = "") -> Volatility:
    """Estimate a player's outcome spread from structural drivers.

    Deliberately additive and small: each driver nudges the positional base
    rather than multiplying into it, so no single unknown can dominate. An
    estimate that swings wildly on one missing field would be worse than the
    VORP-only board it is meant to improve.
    """
    sigma = _POS_BASE.get(str(position).upper(), _DEFAULT_BASE)
    drivers: list[str] = []

    # Role certainty. A committee back's week-to-week usage is the single
    # biggest swing factor we can see without game logs.
    if depth is not None:
        if depth >= 3:
            sigma += 0.10
            drivers.append("buried on the depth chart")
        elif depth == 2:
            sigma += 0.06
            drivers.append("committee role")
        elif depth == 1:
            sigma -= 0.03
            drivers.append("clear starter")

    # Thin sample = thin projection. Fewer games means we know less, and not
    # knowing is itself a form of variance.
    if games_2025 is not None:
        if games_2025 <= 8:
            sigma += 0.09
            drivers.append(f"only {games_2025:.0f} games in 2025")
        elif games_2025 <= 13:
            sigma += 0.04
            drivers.append("partial 2025 sample")

    # Age curve. Decline is not smooth; it arrives in a bad month.
    if age_factor < 0.95:
        sigma += 0.05
        drivers.append("past the age curve")

    # A flagged body is a bimodal outcome — plays or doesn't.
    low = str(note).lower()
    if any(w in low for w in ("questionable", "doubtful", "injur", "out")):
        sigma += 0.08
        drivers.append("injury flag")

    sigma = max(0.15, min(0.85, sigma))

    # ~10th/90th percentile of a SEASON, derived from the weekly spread:
    #
    #   weekly sd  = sigma * (proj / 17)
    #   season sd  = weekly sd * sqrt(17) = sigma * proj / sqrt(17)
    #   p90        = proj + 1.2816 * season sd
    #
    # The sqrt(17) is the whole point: week-to-week noise partially cancels
    # across a season, so the season range is far tighter than the weekly one.
    # An earlier version applied the 1.2816 z-score AND a further 2.2 multiplier,
    # double-counting it and inflating every ceiling on the board — caught by
    # test_season_range_is_damped_relative_to_weekly_spread, which is there
    # precisely because an over-generous ceiling is the failure nobody notices.
    season_sd = sigma * proj_points / (17 ** 0.5)
    ceiling = proj_points + 1.2816 * season_sd
    floor = max(0.0, proj_points - 1.2816 * season_sd)

    label = "SWINGY" if sigma >= 0.46 else ("STEADY" if sigma <= 0.32 else "BALANCED")
    return Volatility(
        sigma_pct=round(sigma, 3),
        ceiling=round(ceiling, 1),
        floor=round(floor, 1),
        label=label,
        drivers=", ".join(drivers) if drivers else "positional baseline only",
    )


def draft_posture(label: str, *, chasing: bool) -> str:
    """One line on whether this shape suits your position in the table.

    Encodes the finding that made this module worth writing: variance is not
    good or bad, it is directional. Chasing the leader, you need outcomes they
    cannot match. Protecting a lead, you need the weeks not to blow up.
    """
    if chasing:
        return {"SWINGY": "take it — you cannot catch anyone by matching them",
                "BALANCED": "fine",
                "STEADY": "safe, and safe does not close a gap"}.get(label, "fine")
    return {"SWINGY": "risky with a lead — one dead week undoes a month",
            "BALANCED": "fine",
            "STEADY": "take it — protects the lead"}.get(label, "fine")
