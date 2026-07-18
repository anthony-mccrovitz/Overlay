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
