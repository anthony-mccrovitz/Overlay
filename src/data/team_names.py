"""
Canonical team name mapping across data sources.

Every data source (Barttorvik, Kaggle, Odds API) uses different team names.
This module maps all variants to a single canonical name and raises ValueError
on unknown teams — loud failure beats silent data corruption.
"""

# Canonical name → list of known aliases (Barttorvik, Kaggle, Odds API variants)
_ALIASES: dict[str, list[str]] = {
    "Alabama": ["Alabama", "Bama"],
    "Arizona": ["Arizona", "Ariz"],
    "Arizona St": ["Arizona St", "Arizona State", "Arizona St."],
    "Arkansas": ["Arkansas", "Ark"],
    "Auburn": ["Auburn"],
    "Baylor": ["Baylor"],
    "Boise St": ["Boise St", "Boise State", "Boise St."],
    "BYU": ["BYU", "Brigham Young"],
    "Butler": ["Butler"],
    "Cal": ["Cal", "California", "UC Berkeley"],
    "Cincinnati": ["Cincinnati", "Cincy"],
    "Clemson": ["Clemson"],
    "Cleveland St": ["Cleveland St", "Cleveland State", "Cleveland St."],
    "Colorado": ["Colorado", "Colo"],
    "Colorado St": ["Colorado St", "Colorado State", "Colorado St."],
    "Connecticut": ["Connecticut", "UConn", "CONN"],
    "Creighton": ["Creighton"],
    "Dayton": ["Dayton"],
    "Drake": ["Drake"],
    "Duke": ["Duke"],
    "Florida": ["Florida", "Fla"],
    "Florida St": ["Florida St", "Florida State", "Florida St."],
    "Gonzaga": ["Gonzaga"],
    "Grand Canyon": ["Grand Canyon", "GCU", "Grand Canyon Univ"],
    "Houston": ["Houston"],
    "Illinois": ["Illinois", "Ill"],
    "Indiana": ["Indiana", "Ind"],
    "Iowa": ["Iowa"],
    "Iowa St": ["Iowa St", "Iowa State", "Iowa St."],
    "James Madison": ["James Madison", "JMU"],
    "Kansas": ["Kansas", "Kan"],
    "Kansas St": ["Kansas St", "Kansas State", "Kansas St.", "K-State"],
    "Kentucky": ["Kentucky", "UK"],
    "Liberty": ["Liberty"],
    "Louisville": ["Louisville"],
    "Loyola Chicago": ["Loyola Chicago", "Loyola-Chicago", "Loyola IL"],
    "LSU": ["LSU", "Louisiana State"],
    "Marquette": ["Marquette"],
    "Maryland": ["Maryland", "Md"],
    "McNeese": ["McNeese", "McNeese State", "McNeese St", "McNeese St."],
    "Memphis": ["Memphis"],
    "Miami FL": ["Miami FL", "Miami (FL)", "Miami"],
    "Miami OH": ["Miami OH", "Miami (OH)", "Miami Ohio"],
    "Michigan": ["Michigan", "Mich"],
    "Michigan St": ["Michigan St", "Michigan State", "Michigan St.", "MSU"],
    "Minnesota": ["Minnesota", "Minn"],
    "Mississippi": ["Mississippi", "Ole Miss"],
    "Mississippi St": ["Mississippi St", "Mississippi State", "Mississippi St.", "Miss St"],
    "Missouri": ["Missouri", "Mizzou"],
    "Montana St": ["Montana St", "Montana State", "Montana St."],
    "NC State": ["NC State", "North Carolina State", "N.C. State"],
    "Nebraska": ["Nebraska", "Neb"],
    "Nevada": ["Nevada"],
    "New Mexico": ["New Mexico", "N Mexico"],
    "North Carolina": ["North Carolina", "UNC", "N Carolina"],
    "Northwestern": ["Northwestern", "NW"],
    "Notre Dame": ["Notre Dame", "N Dame"],
    "Oakland": ["Oakland"],
    "Ohio St": ["Ohio St", "Ohio State", "Ohio St."],
    "Oklahoma": ["Oklahoma", "Okla"],
    "Oklahoma St": ["Oklahoma St", "Oklahoma State", "Oklahoma St."],
    "Oregon": ["Oregon", "Ore"],
    "Oregon St": ["Oregon St", "Oregon State", "Oregon St."],
    "Penn St": ["Penn St", "Penn State", "Penn St."],
    "Pittsburgh": ["Pittsburgh", "Pitt"],
    "Providence": ["Providence"],
    "Purdue": ["Purdue"],
    "Rutgers": ["Rutgers"],
    "Saint Mary's": ["Saint Mary's", "St. Mary's", "St Mary's", "Saint Marys", "St. Marys", "St Mary's CA", "St. Mary's CA", "Saint Mary's CA"],
    "San Diego St": ["San Diego St", "San Diego State", "San Diego St.", "SDSU"],
    "Seton Hall": ["Seton Hall"],
    "South Carolina": ["South Carolina", "S Carolina"],
    "SMU": ["SMU", "Southern Methodist"],
    "St. John's": ["St. John's", "Saint John's", "St Johns", "St. Johns", "St John's"],
    "St. Peter's": ["St. Peter's", "Saint Peter's", "St Peters"],
    "Stanford": ["Stanford"],
    "Syracuse": ["Syracuse", "Cuse"],
    "TCU": ["TCU", "Texas Christian"],
    "Temple": ["Temple"],
    "Tennessee": ["Tennessee", "Tenn"],
    "Texas": ["Texas", "Tex"],
    "Texas A&M": ["Texas A&M", "Texas AM", "TAMU"],
    "Texas Tech": ["Texas Tech", "Tex Tech"],
    "Toledo": ["Toledo"],
    "Tulane": ["Tulane"],
    "UAB": ["UAB", "Alabama Birmingham"],
    "UCLA": ["UCLA"],
    "UNLV": ["UNLV", "Nevada Las Vegas"],
    "USC": ["USC", "Southern California", "Southern Cal"],
    "Utah": ["Utah"],
    "Utah St": ["Utah St", "Utah State", "Utah St."],
    "Vanderbilt": ["Vanderbilt", "Vandy"],
    "Vermont": ["Vermont"],
    "Villanova": ["Villanova", "Nova"],
    "Virginia": ["Virginia", "UVA"],
    "Virginia Tech": ["Virginia Tech", "Va Tech", "VT"],
    "Wake Forest": ["Wake Forest"],
    "Washington": ["Washington", "Wash"],
    "Washington St": ["Washington St", "Washington State", "Washington St."],
    "West Virginia": ["West Virginia", "W Virginia", "WVU"],
    "Wichita St": ["Wichita St", "Wichita State", "Wichita St."],
    "Wisconsin": ["Wisconsin", "Wisc"],
    "Xavier": ["Xavier"],
    "Yale": ["Yale"],
    # Tournament + KenPom teams not in original list
    "Georgia": ["Georgia", "UGA"],
    "Santa Clara": ["Santa Clara"],
    "St Louis": ["St Louis", "Saint Louis", "St. Louis"],
    "VCU": ["VCU", "Virginia Commonwealth"],
    "South Florida": ["South Florida", "USF"],
    "UCF": ["UCF", "Central Florida"],
    "Akron": ["Akron"],
    "Northern Iowa": ["Northern Iowa", "UNI", "N Iowa"],
    "Cal Baptist": ["Cal Baptist", "California Baptist", "CBU"],
    "N Dakota St": ["N Dakota St", "North Dakota State", "North Dakota St", "NDSU", "N Dakota St."],
    "Furman": ["Furman"],
    "Siena": ["Siena"],
    "Troy": ["Troy"],
    "Penn": ["Penn", "Pennsylvania"],
    "Idaho": ["Idaho"],
    "Lehigh": ["Lehigh"],
    "Prairie View": ["Prairie View", "Prairie View A&M"],
    "Hofstra": ["Hofstra"],
    "Wright St": ["Wright St", "Wright State", "Wright St."],
    "Tennessee St": ["Tennessee St", "Tennessee State", "Tennessee St."],
    "Howard": ["Howard"],
    "UMBC": ["UMBC", "Maryland Baltimore County"],
    "High Point": ["High Point"],
    "Hawaii": ["Hawaii", "Hawai'i"],
    "Kennesaw": ["Kennesaw", "Kennesaw State", "Kennesaw St"],
    "Queens NC": ["Queens NC", "Queens University", "Queens"],
    "LIU Brooklyn": ["LIU Brooklyn", "Long Island University", "LIU"],
    "Georgia Tech": ["Georgia Tech", "Ga Tech"],
    "Boston College": ["Boston College", "BC"],
    "DePaul": ["DePaul"],
    "Tulsa": ["Tulsa"],
    "George Mason": ["George Mason", "GMU"],
    "Georgetown": ["Georgetown"],
    "George Washington": ["George Washington", "GW"],
    "Belmont": ["Belmont"],
    "App State": ["App State", "Appalachian State", "Appalachian St"],
    "Murray State": ["Murray State", "Murray St"],
    "Davidson": ["Davidson"],
    "Richmond": ["Richmond"],
    "San Francisco": ["San Francisco", "USF SF"],
    "Loyola Marymount": ["Loyola Marymount", "LMU"],
    "Wyoming": ["Wyoming"],
    "Charleston": ["Charleston", "College of Charleston"],
    "Florida Atlantic": ["Florida Atlantic", "FAU"],
    "Western Kentucky": ["Western Kentucky", "WKU"],
    "Colgate": ["Colgate"],
    "Cornell": ["Cornell"],
    "Princeton": ["Princeton"],
    "Iona": ["Iona"],
    "Samford": ["Samford"],
    "Ohio": ["Ohio", "Ohio University"],
    "Wofford": ["Wofford"],
}

# Build reverse lookup: alias → canonical name
_LOOKUP: dict[str, str] = {}
for canonical, aliases in _ALIASES.items():
    for alias in aliases:
        lower = alias.lower().strip()
        if lower in _LOOKUP:
            raise RuntimeError(
                f"Duplicate alias '{alias}' maps to both "
                f"'{_LOOKUP[lower]}' and '{canonical}'"
            )
        _LOOKUP[lower] = canonical
    # Also map canonical name itself
    lower_canonical = canonical.lower().strip()
    if lower_canonical not in _LOOKUP:
        _LOOKUP[lower_canonical] = canonical


def normalize(name: str) -> str:
    """
    Map any team name variant to its canonical form.
    Raises ValueError if the team is unknown — loud failure prevents
    silent data corruption in downstream joins.
    """
    key = name.lower().strip()
    if key in _LOOKUP:
        return _LOOKUP[key]

    # Try stripping common suffixes/prefixes
    for suffix in [" university", " univ", " college", " st.", " state"]:
        stripped = key.replace(suffix, "").strip()
        if stripped in _LOOKUP:
            return _LOOKUP[stripped]

    # Try stripping mascot names (e.g., "Duke Blue Devils" → "Duke")
    # Walk backwards removing words until we find a match
    words = key.split()
    for i in range(len(words), 0, -1):
        prefix = " ".join(words[:i])
        if prefix in _LOOKUP:
            return _LOOKUP[prefix]

    raise ValueError(
        f"Unknown team name: '{name}'. "
        f"Add it to src/data/team_names.py _ALIASES dict."
    )



def try_normalize(name: str) -> str | None:
    """Like normalize() but returns None instead of raising on unknown teams."""
    try:
        return normalize(name)
    except ValueError:
        return None


