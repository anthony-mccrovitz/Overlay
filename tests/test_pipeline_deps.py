"""The light dependency set must carry everything the grading path imports.

The bug this locks down: `_pipeline.yml` installs two different dependency
sets. `level: full` installs requirements.txt; `level: light` installs a
hand-written list. openpyxl>=3.1 was in requirements.txt but NOT in the light
list, and pandas needs it to read .xlsx.

So tennis *picks* (tennis.yml, level full) generated fine every day while
tennis *grading* (nightly.yml, level light) raised ImportError inside
pd.read_excel on every run from 2026-07-12 to 2026-08-12. load_matches caught
that exception and returned an empty frame, which the grader reported as
"match not in source yet" — the same words it uses for healthy waiting. 362
picks accrued as permanently pending while every nightly run finished green.

The lesson generalized: a dependency the light path needs at RUNTIME cannot
live only in requirements.txt. requirements.txt is not the contract for light
jobs; the list in _pipeline.yml is.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / ".github" / "workflows" / "_pipeline.yml"

# Modules the light-level jobs import while grading, mapped to the pip package
# that provides them. Grading runs at level "light" (nightly.yml, grade-live,
# monitor), so each of these must appear in the light install list.
#   pandas/numpy  — every ledger read
#   openpyxl      — tennis-data.co.uk .xlsx workbooks (the 2026-08 outage)
#   requests      — every scores API
#   scipy         — calibration / promotion-gate stats
REQUIRED_LIGHT_PACKAGES = {
    "pandas",
    "numpy",
    "requests",
    "scipy",
    "openpyxl",
    # nba_api — NBA prop grading (_fetch_nba_player_stats) runs in nightly.yml,
    # which is level "light".
    "nba_api",
}

# Third-party modules imported anywhere in the grading/model path. Every one
# must be declared in requirements.txt, or a dev machine that happens to have
# it installed will pass while CI silently degrades.
REQUIRED_DECLARED_PACKAGES = {
    "openpyxl": "openpyxl",
    "nba_api": "nba_api",
    # statsmodels — NegBinPropModel.fit(), reached by the weekly retrain.
    "statsmodels": "statsmodels",
    # playwright — nightly_recap.py renders the recap card to PNG.
    "playwright": "playwright",
}


def _light_install_list() -> str:
    """The pip install command used when level != full, comments stripped.

    Comments must go: this block documents the openpyxl outage by name, and a
    substring match against the prose would report the package as installed
    while the actual pip line lacked it — passing for the very regression the
    test exists to catch. (It did, on the first draft.)
    """
    text = PIPELINE.read_text()
    # The else-branch of the level check is the light install.
    m = re.search(r"else\s*\n(.*?)\n\s*fi", text, re.DOTALL)
    assert m, "could not locate the light-level install block in _pipeline.yml"
    lines = [ln for ln in m.group(1).splitlines()
             if not ln.lstrip().startswith("#")]
    block = "\n".join(lines)
    assert "pip install" in block, (
        "the light-level block has no pip install command — the parse is stale"
    )
    return block


@pytest.mark.parametrize("package", sorted(REQUIRED_LIGHT_PACKAGES))
def test_light_level_installs_required_package(package):
    block = _light_install_list()
    assert re.search(rf"(?<![\w-]){re.escape(package)}(?![\w-])", block), (
        f"{package!r} is missing from the light dependency list in "
        f"{PIPELINE.relative_to(ROOT)}.\n\n"
        f"Light-level jobs (nightly grading, live grader, integrity monitor) "
        f"import it at runtime. Putting it only in requirements.txt is not "
        f"enough — requirements.txt is installed for level 'full' ONLY.\n\n"
        f"This is exactly how tennis grading died silently for a month: "
        f"openpyxl was in requirements.txt, absent here, and pd.read_excel's "
        f"ImportError was swallowed into 'match not in source yet'."
    )


@pytest.mark.parametrize("module,package", sorted(REQUIRED_DECLARED_PACKAGES.items()))
def test_imported_modules_are_declared_in_requirements(module, package):
    """A dependency that exists only on someone's laptop is not a dependency.

    nba_api was imported by src/data/wnba_stats.py and grade.py for months
    while appearing in NO requirements file. It was installed on the dev
    machine, so every local run worked; every CI run — including level "full",
    which installs requirements.txt — hit ImportError, caught it, and carried
    on with league-average defaults. wnba/total and wnba/spread read DARK in
    the integrity monitor the whole time, and NBA props graded nothing.
    """
    req = (ROOT / "requirements.txt").read_text()
    declared = [ln.split("#")[0].strip() for ln in req.splitlines()]
    declared = [ln for ln in declared if ln]
    assert any(ln.split("==")[0].split(">=")[0].strip() == package
               for ln in declared), (
        f"{module!r} is imported by the codebase but {package!r} is not in "
        f"requirements.txt. It will import fine on any machine that already "
        f"has it and fail silently everywhere else."
    )


def test_openpyxl_actually_imports_and_reads_xlsx():
    """Belt and braces: the package must be present in THIS environment too.

    A green CI matrix that can't open a workbook is the failure we shipped.
    """
    openpyxl = pytest.importorskip("openpyxl")
    assert openpyxl.__version__

    import pandas as pd
    # Prove pandas can round-trip an .xlsx through the openpyxl engine.
    import io
    buf = io.BytesIO()
    pd.DataFrame({"Winner": ["a"], "Loser": ["b"]}).to_excel(buf, index=False)
    buf.seek(0)
    assert len(pd.read_excel(buf)) == 1
