"""
src/util/determinism.py — Global reproducibility seed.

Any pick generator that must be bit-for-bit reproducible calls seed_everything()
once at startup. Two runs on the same inputs must produce the same picks; a model
that can't reproduce its own number can't be trusted or debugged (see the World
Cup Argentina-45.7%-vs-England-41.6% phantom that motivated this).

This seeds Python's `random`, NumPy's global RNG, and PYTHONHASHSEED-sensitive
paths. It does NOT make network fetches deterministic — those are frozen
separately by caching their responses (see soccer_model_v2.seed_from_eloratings).
"""
from __future__ import annotations

import os
import random

# One fixed seed for the whole project. Arbitrary but constant.
GLOBAL_SEED = 1729


def seed_everything(seed: int = GLOBAL_SEED) -> int:
    """Seed every RNG we touch. Call once at the top of a pick generator.

    Returns the seed used, so callers can log it.
    """
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except Exception:
        pass
    return seed
