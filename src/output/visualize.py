"""
Bracket and tournament visualization.

Generates:
1. Color-coded bracket (green=lock, yellow=toss-up, red=upset)
2. Advancement probability chart (FiveThirtyEight-style)
3. Confidence heatmap
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns


OUTPUT_DIR = Path("output")


def plot_advancement_probs(
    adv_df: pd.DataFrame,
    team_names: dict,
    year: int = 2026,
    top_n: int = 16,
    save: bool = True,
) -> str:
    """
    Plot advancement probabilities as a horizontal bar chart.
    Shows each team's probability of reaching each round.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = adv_df.head(top_n).copy()
    df["Name"] = df["TeamID"].map(team_names).fillna(df["TeamID"].astype(str))
    df["Label"] = df.apply(lambda r: f"({int(r['SeedNum'])}) {r['Name']}", axis=1)
    df = df.iloc[::-1]  # Reverse for bottom-to-top plotting

    rounds = ["R64", "R32", "S16", "E8", "F4", "Championship"]
    colors = ["#2ecc71", "#27ae60", "#f39c12", "#e67e22", "#e74c3c", "#c0392b"]
    round_labels = ["R64", "R32", "Sweet 16", "Elite 8", "Final Four", "Champion"]

    fig, ax = plt.subplots(figsize=(12, max(6, top_n * 0.4)))

    y = np.arange(len(df))
    left = np.zeros(len(df))

    for i, (round_col, color, label) in enumerate(zip(rounds, colors, round_labels)):
        if round_col not in df.columns:
            continue
        widths = df[round_col].values
        ax.barh(y, widths, left=left, height=0.7, color=color, label=label, alpha=0.85)
        left = left + widths  # Not cumulative — these are independent probabilities

    # Since these are independent probs (not cumulative), use just the columns directly
    # Actually, let's plot them as grouped bars or just championship probability
    ax.clear()

    # Simpler: just show championship probability + color by seed
    champ_probs = df["Championship"].values
    bar_colors = [_seed_color(s) for s in df["SeedNum"].values]

    bars = ax.barh(y, champ_probs, height=0.7, color=bar_colors, alpha=0.85)

    # Add percentage labels
    for bar, prob in zip(bars, champ_probs):
        if prob > 0.005:
            ax.text(
                bar.get_width() + 0.005, bar.get_y() + bar.get_height() / 2,
                f"{prob:.1%}", va="center", fontsize=9,
            )

    ax.set_yticks(y)
    ax.set_yticklabels(df["Label"].values, fontsize=10)
    ax.set_xlabel("Championship Probability", fontsize=12)
    ax.set_title(f"March Madness {year} — Championship Odds (Monte Carlo)", fontsize=14, fontweight="bold")
    ax.set_xlim(0, min(1, champ_probs.max() * 1.3 + 0.02))

    # Add seed color legend
    seed_patches = [
        mpatches.Patch(color="#2ecc71", label="1-4 seeds"),
        mpatches.Patch(color="#f39c12", label="5-8 seeds"),
        mpatches.Patch(color="#e74c3c", label="9-12 seeds"),
        mpatches.Patch(color="#95a5a6", label="13-16 seeds"),
    ]
    ax.legend(handles=seed_patches, loc="lower right", fontsize=9)

    plt.tight_layout()

    path = OUTPUT_DIR / f"advancement_{year}.png"
    if save:
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return str(path)

    plt.close(fig)
    return ""


def plot_confidence_heatmap(
    bracket,
    year: int = 2026,
    save: bool = True,
) -> str:
    """
    Plot a heatmap of prediction confidence across all bracket games.
    Green = high confidence, red = toss-up.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    round_names = {1: "R64", 2: "R32", 3: "S16", 4: "E8", 5: "F4", 6: "Final"}

    fig, axes = plt.subplots(1, 6, figsize=(18, 6), gridspec_kw={"width_ratios": [8, 4, 2, 1, 1, 1]})

    for round_num in range(1, 7):
        ax = axes[round_num - 1]
        games = bracket.get_round(round_num)

        if not games:
            ax.set_visible(False)
            continue

        confidences = [g.confidence for g in games]
        labels = [
            f"({g.team_a_seed}){g.team_a_name[:10]} v\n({g.team_b_seed}){g.team_b_name[:10]}"
            for g in games
        ]

        # Color: green (confident) → yellow (moderate) → red (toss-up)
        colors = [_confidence_color(c) for c in confidences]

        y = np.arange(len(games))
        bars = ax.barh(y, confidences, color=colors, height=0.8)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=7)
        ax.set_title(round_names[round_num], fontsize=10, fontweight="bold")
        ax.set_xlim(0, 0.5)
        ax.invert_yaxis()

    plt.suptitle(
        f"March Madness {year} — Prediction Confidence by Round",
        fontsize=14, fontweight="bold",
    )
    plt.tight_layout()

    path = OUTPUT_DIR / f"confidence_{year}.png"
    if save:
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return str(path)

    plt.close(fig)
    return ""


def _seed_color(seed: int) -> str:
    """Map seed to color for visualizations."""
    if seed <= 4:
        return "#2ecc71"
    elif seed <= 8:
        return "#f39c12"
    elif seed <= 12:
        return "#e74c3c"
    else:
        return "#95a5a6"


def _confidence_color(confidence: float) -> str:
    """Map confidence (0-0.5) to color. Higher = greener."""
    if confidence > 0.3:
        return "#2ecc71"  # Green — lock
    elif confidence > 0.15:
        return "#f39c12"  # Yellow — moderate
    elif confidence > 0.05:
        return "#e67e22"  # Orange — uncertain
    else:
        return "#e74c3c"  # Red — toss-up
