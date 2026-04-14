from src.betting.kelly import kelly_fraction


def test_kelly_fraction_positive_edge():
    # +150 implies 40%; model says 50% => positive edge
    frac = kelly_fraction(model_prob=0.50, american_odds=150, fraction=0.5)
    assert frac > 0


def test_kelly_fraction_no_edge_returns_zero():
    # -200 implies ~66.7%; model says 55% => no edge
    frac = kelly_fraction(model_prob=0.55, american_odds=-200, fraction=0.5)
    assert frac == 0.0


def test_kelly_fraction_full_vs_half():
    full = kelly_fraction(model_prob=0.55, american_odds=110, fraction=1.0)
    half = kelly_fraction(model_prob=0.55, american_odds=110, fraction=0.5)
    assert half == full * 0.5
