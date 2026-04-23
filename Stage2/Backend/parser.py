import re

COUNTRY_NAME_TO_CODE: dict[str, str] = {
    # Africa (primary focus)
    "nigeria": "NG",
    "kenya": "KE",
    "ghana": "GH",
    "tanzania": "TZ",
    "south africa": "ZA",
    "ethiopia": "ET",
    "egypt": "EG",
    "uganda": "UG",
    "rwanda": "RW",
    "senegal": "SN",
    "ivory coast": "CI",
    "cote d'ivoire": "CI",
    "cameroon": "CM",
    "angola": "AO",
    "benin": "BJ",
    "togo": "TG",
    "mali": "ML",
    "niger": "NE",
    "burkina faso": "BF",
    "chad": "TD",
    "sudan": "SD",
    "zambia": "ZM",
    "zimbabwe": "ZW",
    "mozambique": "MZ",
    "malawi": "MW",
    "botswana": "BW",
    "namibia": "NA",
    "madagascar": "MG",
    "morocco": "MA",
    "tunisia": "TN",
    "algeria": "DZ",
    "libya": "LY",
    "somalia": "SO",
    "eritrea": "ER",
    "djibouti": "DJ",
    "comoros": "KM",
    "mauritius": "MU",
    "seychelles": "SC",
    "cape verde": "CV",
    "guinea-bissau": "GW",
    "guinea bissau": "GW",
    "equatorial guinea": "GQ",
    "sierra leone": "SL",
    "liberia": "LR",
    "gambia": "GM",
    "guinea": "GN",
    "democratic republic of congo": "CD",
    "dr congo": "CD",
    "drc": "CD",
    "central african republic": "CF",
    "republic of congo": "CG",
    "congo": "CG",
    "gabon": "GA",
    "sao tome": "ST",
    "burundi": "BI",
    "south sudan": "SS",
    "lesotho": "LS",
    "eswatini": "SZ",
    "swaziland": "SZ",
    # Rest of world
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "france": "FR",
    "germany": "DE",
    "italy": "IT",
    "spain": "ES",
    "portugal": "PT",
    "brazil": "BR",
    "india": "IN",
    "china": "CN",
    "japan": "JP",
    "canada": "CA",
    "australia": "AU",
    "mexico": "MX",
    "argentina": "AR",
    "colombia": "CO",
    "indonesia": "ID",
    "pakistan": "PK",
    "bangladesh": "BD",
    "russia": "RU",
    "turkey": "TR",
    "iran": "IR",
    "iraq": "IQ",
    "saudi arabia": "SA",
    "uae": "AE",
    "united arab emirates": "AE",
}

# Sort longest names first so multi-word names match before substrings
_SORTED_COUNTRIES = sorted(COUNTRY_NAME_TO_CODE.keys(), key=len, reverse=True)


def parse_natural_language(q: str) -> dict | None:
    """
    Parse a plain-English query into filter kwargs.
    Returns None if the query cannot be interpreted.
    """
    text = q.lower().strip()
    filters: dict = {}

    # --- Gender ---
    both = re.search(r"\b(male\s+and\s+female|female\s+and\s+male)\b", text)
    if not both:
        if re.search(r"\b(males?|men|man)\b", text):
            filters["gender"] = "male"
        elif re.search(r"\b(females?|women|woman|girls?)\b", text):
            filters["gender"] = "female"

    # --- Age group ---
    if re.search(r"\b(children|child|kids?)\b", text):
        filters["age_group"] = "child"
    elif re.search(r"\b(teenagers?|teens?|adolescents?)\b", text):
        filters["age_group"] = "teenager"
    elif re.search(r"\b(adults?)\b", text):
        filters["age_group"] = "adult"
    elif re.search(r"\b(seniors?|elderly|elders?)\b", text):
        filters["age_group"] = "senior"

    # "young" → ages 16–24 (only when no explicit age_group)
    if re.search(r"\b(young|youth)\b", text) and "age_group" not in filters:
        filters["min_age"] = 16
        filters["max_age"] = 24

    # --- Numeric age constraints ---
    between = re.search(r"\bbetween\s+(\d+)\s+and\s+(\d+)\b", text)
    if between:
        filters["min_age"] = int(between.group(1))
        filters["max_age"] = int(between.group(2))
    else:
        above = re.search(r"\b(?:above|over|older\s+than)\s+(\d+)\b", text)
        if above:
            filters["min_age"] = int(above.group(1))

        below = re.search(r"\b(?:below|under|younger\s+than)\s+(\d+)\b", text)
        if below:
            filters["max_age"] = int(below.group(1))

    # --- Country ---
    for country_name in _SORTED_COUNTRIES:
        pattern = r"\b" + re.escape(country_name) + r"\b"
        if re.search(pattern, text):
            filters["country_id"] = COUNTRY_NAME_TO_CODE[country_name]
            break

    if not filters:
        return None

    return filters
