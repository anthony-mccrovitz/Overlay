from pathlib import Path

from src.output.pick_card import generate_pick_card_image, generate_pick_card_text


def _sample_picks():
    return [
        {
            "Team": "Iowa State Cyclones",
            "Opponent": "Kansas Jayhawks",
            "Edge": 0.082,
            "BestOdds": -184,
            "ModelProb": 0.65,
            "ImpliedProb": 0.55,
            "BetSize": 21.0,
            "Why": "Superior efficiency profile.",
        }
    ]


def test_generate_pick_card_text_happy_path():
    text = generate_pick_card_text(_sample_picks(), sport="ncaab")
    assert "ChefTonyBets" in text
    assert "NCAAB" in text
    assert "Iowa State" in text
    assert "8.2%" in text  # edge formatted as percentage


def test_generate_pick_card_text_high_confidence_label():
    text = generate_pick_card_text(_sample_picks(), sport="ncaab")
    # Edge of 8.2% >= 6% → HIGH confidence
    assert "HIGH" in text


def test_generate_pick_card_text_empty_state():
    text = generate_pick_card_text([])
    assert "No value bets identified today." in text


def test_generate_pick_card_text_long_team_names():
    picks = [
        {
            "Team": "University of Southern California Trojans",
            "Opponent": "University of California Los Angeles Bruins",
            "Edge": 0.04,
            "BestOdds": -110,
            "ModelProb": 0.55,
        }
    ]
    text = generate_pick_card_text(picks, sport="ncaab")
    assert "ChefTonyBets" in text
    assert "University of Southern California" in text


def test_generate_pick_card_text_missing_stats():
    picks = [{"Team": "TeamA", "Opponent": "TeamB"}]
    text = generate_pick_card_text(picks, sport="mlb")
    assert "TeamA" in text


def test_generate_pick_card_image_returns_path_or_none():
    # Returns a Path when Pillow is installed, None if not.
    result = generate_pick_card_image(_sample_picks(), sport="ncaab")
    assert result is None or (isinstance(result, Path) and result.suffix == ".png")


def test_generate_pick_card_image_empty_picks():
    result = generate_pick_card_image([], sport="ncaab")
    # Should not crash regardless of whether Pillow is installed.
    assert result is None or isinstance(result, Path)
