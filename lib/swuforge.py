"""SWU Forge (swuforge.com) deck loader.

SWU Forge serves each public deck as the standard SWU deck-export JSON at
``/api/decks/{id}/export``::

    {"metadata": {"name": ..., "author": ...},
     "leader": {"id": "ASH_009", "count": 1},
     "secondleader": {...},            # Twin Suns only
     "base": {"id": "HMW_031", "count": 1},
     "deck": [{"id": "ASH_108", "count": 2}, ...],
     "sideboard": [...]}

That export carries only set + number ids, so ``fetch_deck`` fills in each
card's name, subtitle, type, and aspects from the local swu-db cache and
returns a payload shaped like SWUDB's ``/api/deck/{id}`` response. Every
script that already understands a SWUDB deck then works unchanged.
"""

import re
from urllib.parse import urlparse

import pandas as pd
import requests

from lib.swudb import get_swu_list

EXPORT_URL = "https://swuforge.com/api/decks/{deck_id}/export"
# The deck page's own data (SvelteKit). Only used to read the deck's format,
# which the export leaves out.
PAGE_DATA_URL = "https://swuforge.com/decks/{deck_id}/__data.json"

# SWU Forge format slugs -> the format names used across these scripts.
FORMAT_NAMES = {
    "premier": "Premier",
    "eternal": "Eternal",
    "twin-suns": "Twin Suns",
    "limited": "Limited",
}

# SWUDB's numeric ids, so the converted payload matches a real SWUDB one.
ASPECT_IDS = {
    "Aggression": 1,
    "Command": 2,
    "Cunning": 3,
    "Vigilance": 4,
    "Heroism": 5,
    "Villainy": 6,
}
TYPE_IDS = {"Leader": 0, "Base": 1, "Unit": 2, "Event": 3, "Upgrade": 4}

# "A deck can have up to 15 copies of this card." (Swarming Vulture Droid)
_COPY_LIMIT_RE = re.compile(r"deck can have up to (\d+) copies", re.IGNORECASE)

_set_frames = {}


def is_swuforge_url(input_str):
    """Check if input is a SWU Forge deck URL."""
    try:
        parsed = urlparse(input_str)
    except Exception:
        return False
    return parsed.netloc in ("swuforge.com", "www.swuforge.com") and extract_deck_id(input_str) is not None


def extract_deck_id(url):
    """Extract the deck id from https://swuforge.com/decks/{id}."""
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "decks" and parts[1]:
        return parts[1]
    return None


def fetch_export(url, timeout=30):
    """Fetch the raw SWU Forge export JSON for a deck URL."""
    deck_id = extract_deck_id(url)
    if not deck_id:
        raise ValueError(f"Could not extract deck ID from URL: {url}")

    api_url = EXPORT_URL.format(deck_id=deck_id)
    response = requests.get(api_url, timeout=timeout)
    if response.status_code == 404:
        raise ValueError(
            f"Deck not found at {api_url} (404). "
            "If the deck page loads in a browser when you are signed in, it is "
            "likely private — SWU Forge only exports decks with link sharing on."
        )
    response.raise_for_status()
    return response.json()


def fetch_declared_format(deck_id, timeout=30):
    """The format the deck's owner picked on SWU Forge ('Premier', 'Eternal',
    'Twin Suns', 'Limited'), or None if it can't be read.

    The export has no format field, so this reads the deck page's data file.
    That file is SvelteKit's flattened ("devalue") encoding: a list where each
    object's values are indexes back into the same list. Best effort — any
    failure or unexpected shape returns None and callers infer the format.
    """
    try:
        response = requests.get(PAGE_DATA_URL.format(deck_id=deck_id), timeout=timeout)
        response.raise_for_status()
        for node in response.json().get("nodes") or []:
            data = (node or {}).get("data")
            if not isinstance(data, list) or not data or not isinstance(data[0], dict):
                continue
            if "deck" not in data[0]:
                continue
            deck = data[data[0]["deck"]]
            slug = data[deck["format"]]
            return FORMAT_NAMES.get(slug)
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None
    return None


def _set_frame(set_abbr):
    """Cached swu-db card list for a set (numbers zero-padded), or None."""
    key = set_abbr.lower()
    if key not in _set_frames:
        frame = get_swu_list(key, allow_unknown=True)
        if frame is not None:
            frame = frame.copy()
            frame["Number"] = frame["Number"].astype(str).str.zfill(3)
        _set_frames[key] = frame
    return _set_frames[key]


def _text(value):
    """A cache string field, with missing values (NaN / None) as ''."""
    return value.strip() if isinstance(value, str) else ""


def card_payload(card_id):
    """SWUDB-style card dict for a SWU Forge card id like 'ASH_108'.

    Unknown cards (set not cached, number missing) come back as a stub named
    '[ASH_108]' so the deck still loads and the gap is visible.
    """
    set_abbr, _, number = card_id.partition("_")
    set_abbr = set_abbr.upper()
    number = number.zfill(3)
    card = {
        "cardId": None,
        "cardName": f"[{card_id}]",
        "title": "",
        "aspects": [],
        "frontsideAspects": [],
        "type": None,
        "alternativeDeckMaximum": None,
        "defaultImagePath": f"/cards/{set_abbr}/{number}.png",
        "defaultExpansionAbbreviation": set_abbr,
        "defaultCardNumber": number,
    }

    frame = _set_frame(set_abbr)
    if frame is None:
        return card
    rows = frame[frame["Number"] == number]
    if rows.empty:
        return card
    row = rows.iloc[0]

    aspects = row.get("Aspects")
    aspect_ids = [ASPECT_IDS[a] for a in aspects if a in ASPECT_IDS] if isinstance(aspects, list) else []
    cost = pd.to_numeric(row.get("Cost"), errors="coerce")
    limit = _COPY_LIMIT_RE.search(_text(row.get("FrontText")))

    card.update(
        cardName=_text(row.get("Name")) or card["cardName"],
        title=_text(row.get("Subtitle")),
        aspects=aspect_ids,
        frontsideAspects=aspect_ids,
        type=TYPE_IDS.get(_text(row.get("Type"))),
        cost=None if pd.isna(cost) else int(cost),
        alternativeDeckMaximum=int(limit.group(1)) if limit else None,
    )
    return card


def _count(item):
    return int(item.get("count") or 0)


def to_swudb_payload(export, url, declared_format=None):
    """Convert a SWU Forge export into a SWUDB-shaped deck payload.

    ``declared_format`` is the owner's chosen format name (see
    fetch_declared_format); it is the only way to know a deck is Limited.
    """
    metadata = export.get("metadata") or {}

    def single(section):
        item = export.get(section)
        return card_payload(item["id"]) if isinstance(item, dict) and item.get("id") else None

    leader = single("leader")
    second_leader = single("secondleader")
    base = single("base")

    # One entry per printing, with main-deck and sideboard counts side by side.
    entries = {}
    for section, field in (("deck", "count"), ("sideboard", "sideboardCount")):
        for item in export.get(section) or []:
            if not item or not item.get("id") or _count(item) <= 0:
                continue
            entry = entries.setdefault(
                item["id"], {"card": card_payload(item["id"]), "count": 0, "sideboardCount": 0}
            )
            entry[field] += _count(item)

    deck_aspects = sorted(
        {a for card in (leader, second_leader, base) if card for a in card["aspects"]}
    )

    return {
        "deckId": metadata.get("swuforgeDeckId") or extract_deck_id(url),
        "deckUrl": metadata.get("swuforgeDeckUrl") or url,
        "deckName": metadata.get("name") or "Unknown Deck",
        "authorName": metadata.get("author"),
        # SWU Forge's export has no format field: two leaders means Twin Suns.
        "deckFormat": 2 if second_leader else 1,
        "declaredFormat": declared_format,
        "leader": leader,
        "secondLeader": second_leader,
        "base": base,
        "aspects": deck_aspects,
        "shuffledDeck": list(entries.values()),
    }


def fetch_deck(url):
    """Fetch a SWU Forge deck as a SWUDB-shaped payload."""
    export = fetch_export(url)
    return to_swudb_payload(export, url, fetch_declared_format(extract_deck_id(url)))
