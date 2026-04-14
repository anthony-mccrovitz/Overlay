"""
MLB park factors module.

Provides run-factor adjustments based on the home team's ballpark.
A factor > 1.0 indicates a hitter-friendly park (more runs expected),
< 1.0 indicates a pitcher-friendly park.
"""
from __future__ import annotations

PARK_FACTORS: dict[str, float] = {
    "Colorado Rockies":        1.18,   # Coors Field
    "Boston Red Sox":          1.08,   # Fenway
    "Cincinnati Reds":         1.06,   # Great American Ballpark
    "Philadelphia Phillies":   1.04,   # Citizens Bank Park
    "Houston Astros":          1.03,   # Minute Maid Park
    "Texas Rangers":           1.03,   # Globe Life Field
    "Chicago Cubs":            1.02,   # Wrigley Field
    "Baltimore Orioles":       1.02,   # Camden Yards
    "New York Yankees":        1.01,   # Yankee Stadium
    "Atlanta Braves":          1.01,   # Truist Park
    "Kansas City Royals":      1.00,
    "Los Angeles Angels":      1.00,
    "Minnesota Twins":         1.00,
    "New York Mets":           1.00,
    "Arizona Diamondbacks":    0.99,   # Chase Field
    "Washington Nationals":    0.99,
    "St. Louis Cardinals":     0.98,
    "Toronto Blue Jays":       0.98,
    "Cleveland Guardians":     0.97,
    "Miami Marlins":           0.97,
    "Milwaukee Brewers":       0.97,   # American Family Field
    "Detroit Tigers":          0.97,
    "Los Angeles Dodgers":     0.96,
    "Chicago White Sox":       0.96,
    "Oakland Athletics":       0.95,
    "Athletics":               0.95,
    "Tampa Bay Rays":          0.95,   # Tropicana Field (dome)
    "Pittsburgh Pirates":      0.94,
    "Seattle Mariners":        0.93,   # T-Mobile Park
    "San Francisco Giants":    0.92,   # Oracle Park
    "San Diego Padres":        0.91,   # Petco Park
}

# Parks that are outdoors (or open-air enough to be wind-affected).
# Excludes domes and fully retractable-roof parks: Rays, Blue Jays, Astros,
# Rangers, Marlins, Diamondbacks.
OUTDOOR_PARKS: set[str] = {
    "Colorado Rockies",
    "Boston Red Sox",
    "Cincinnati Reds",
    "Philadelphia Phillies",
    "Chicago Cubs",
    "Baltimore Orioles",
    "New York Yankees",
    "Atlanta Braves",
    "Kansas City Royals",
    "Los Angeles Angels",
    "Minnesota Twins",
    "New York Mets",
    "Washington Nationals",
    "St. Louis Cardinals",
    "Cleveland Guardians",
    "Milwaukee Brewers",
    "Detroit Tigers",
    "Los Angeles Dodgers",
    "Chicago White Sox",
    "Oakland Athletics",
    "Athletics",
    "Pittsburgh Pirates",
    "Seattle Mariners",
    "San Francisco Giants",
    "San Diego Padres",
}


def get_park_factor(home_team: str) -> float:
    """Return the run factor for the given home team's park (default 1.0)."""
    return PARK_FACTORS.get(home_team, 1.0)


def apply_park_factor(predicted_total: float, home_team: str) -> float:
    """Multiply predicted total by the home team's park run factor."""
    return predicted_total * get_park_factor(home_team)
