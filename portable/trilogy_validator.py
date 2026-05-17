#!/usr/bin/env python3
"""Validate three SWU decks as a Trilogy build (portable single-file edition).

Premier Trilogy: max 3 copies of any card across all 3 decks combined,
distinct leaders, distinct bases, all decks Premier-legal.

Twin Suns Trilogy Gauntlet (community format): max 1 copy of any card
across all 3 decks combined, distinct leaders, distinct bases, all decks
Twin Suns-legal.

Sources may be SWUDB URLs, .json deck exports, .txt picklists, or sorted
.md files produced by sort_deck_by_set.py. Non-URL sources can't supply
aspect / alternativeDeckMaximum / suspended-name data, so checks that
need that metadata are skipped with a printed note.

----------------------------------------------------------------------
This is a GENERATED, SELF-CONTAINED SNAPSHOT of the swu-tools repo. It
bundles the code that normally lives across trilogy_validator.py,
validate_deck_format.py, sort_deck_by_set.py, lib/deck_source.py, and
lib/swudb.py so it can be handed to someone (e.g. an event judge) with
nothing but `requests` and `pandas` installed and the bundled card_data/
folder alongside it.

Because it is a snapshot, the validation rules (suspensions, set
rotation, set list) are frozen as of generation. If the official rules
change, regenerate this file from the repo. Run `pip install -r
requirements.txt` first if you don't use uv.
----------------------------------------------------------------------
"""

import argparse
import itertools
import json
import math
import os
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

import pandas as pd
import requests

# ======================================================================
# Set constants + card-data cache (from lib/swudb.py)
# ======================================================================

# Main booster/premier-legal sets in release order
MAIN_SETS = ['sor', 'shd', 'twi', 'jtl', 'lof', 'sec', 'law']

# Supplemental product set codes
SPECIAL_SETS = ['ts26']

# Supported set abbreviations for card lookups
VALID_SETS = MAIN_SETS + SPECIAL_SETS

# Uppercase versions for scripts that work with SWUDB deck/set identifiers
MAIN_SETS_UPPER = [set_name.upper() for set_name in MAIN_SETS]
SPECIAL_SETS_UPPER = [set_name.upper() for set_name in SPECIAL_SETS]
VALID_SETS_UPPER = [set_name.upper() for set_name in VALID_SETS]

# Directory for cached card data — bundled alongside this script.
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'card_data')


def get_cache_path(set_name):
    """Get the path to the cached JSON file for a set."""
    return os.path.join(CACHE_DIR, f'{set_name.lower()}.json')


def load_from_cache(set_name):
    """Load card data from local cache if available."""
    cache_path = get_cache_path(set_name)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"{set_name.upper()} Card List Loaded from cache")
            return pd.DataFrame(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load cache for {set_name.upper()}: {e}")
    return None


def save_to_cache(set_name, data):
    """Save card data to local cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = get_cache_path(set_name)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"{set_name.upper()} Card List Saved to cache")
    except IOError as e:
        print(f"Warning: Could not save cache for {set_name.upper()}: {e}")


def get_swu_list(set_name, force_refresh=False):
    """
    Get card list for a set. Checks local cache first, then fetches from API.

    Args:
        set_name: Set abbreviation (sor, shd, twi, jtl, lof, sec)
        force_refresh: If True, skip cache and fetch from API

    Returns:
        DataFrame with card data, or None if failed
    """
    set_name = set_name.lower()

    if set_name not in VALID_SETS:
        print(f"Invalid set: {set_name}. Valid sets: {', '.join(VALID_SETS)}")
        return None

    # Check cache first (unless force refresh)
    if not force_refresh:
        cached_df = load_from_cache(set_name)
        if cached_df is not None:
            return cached_df

    # Fetch from API
    url = f'https://api.swu-db.com/cards/{set_name}'
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        set_json = response.json()
        card_data = set_json.get('data', [])

        if not card_data:
            print(f"Warning: No card data returned for {set_name.upper()}")
            return None

        print(f"{set_name.upper()} Card List Retrieved from API")

        # Save to cache
        save_to_cache(set_name, card_data)

        return pd.DataFrame(card_data)

    except requests.Timeout:
        print(f"Error: Request timed out for {set_name.upper()}")
        return None
    except requests.RequestException as e:
        print(f"Error: Could not fetch {set_name.upper()} from API: {e}")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error: Invalid response for {set_name.upper()}: {e}")
        return None


# ======================================================================
# Deck-file parsers (from sort_deck_by_set.py)
# ======================================================================

# Cache of set card data keyed by lowercase set abbreviation.
_set_cache = {}


def get_card_name_from_api(set_abbr, card_num):
    """Look up card name from swudb API."""
    set_lower = set_abbr.lower()

    if set_abbr not in VALID_SETS_UPPER:
        return None

    # Check cache first
    if set_lower not in _set_cache:
        try:
            url = f'https://api.swu-db.com/cards/{set_lower}'
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                # Build lookup dict by card number
                _set_cache[set_lower] = {
                    card['Number']: card['Name']
                    for card in data.get('data', [])
                }
                print(f"Fetched {set_abbr} card data from API")
            else:
                _set_cache[set_lower] = {}
        except Exception as e:
            print(f"Warning: Could not fetch {set_abbr} data: {e}")
            _set_cache[set_lower] = {}

    # Look up the card
    return _set_cache.get(set_lower, {}).get(card_num)


def parse_set_codes(line):
    """Parse a line of set codes like 'SEC 018, SEC 282, P25 130'."""
    codes = []
    # Match patterns like "SEC 018" or "SOROP 10"
    pattern = r'([A-Z0-9]+)\s+(\d+)'
    matches = re.findall(pattern, line)
    for set_abbr, num in matches:
        codes.append((set_abbr, num.zfill(3)))  # Zero-pad to 3 digits
    return codes


def select_primary_set(set_codes):
    """Select the primary set, preferring main sets over promos."""
    # First, look for a main set
    for set_abbr, num in set_codes:
        if set_abbr in MAIN_SETS_UPPER:
            return (set_abbr, num)

    # Then prefer known supplemental product sets over promos
    for set_abbr, num in set_codes:
        if set_abbr in SPECIAL_SETS_UPPER:
            return (set_abbr, num)

    # Fall back to first listed if no main set found
    return set_codes[0]


def parse_card_id(card_id):
    """Parse a card ID like 'SEC_018' and return card info dict."""
    parts = card_id.split('_')
    if len(parts) == 2:
        set_abbr, num = parts
        num_padded = num.zfill(3)
        # Look up card name from API
        name = get_card_name_from_api(set_abbr, num_padded)
        if not name:
            name = f"[{card_id}]"  # Fallback if API lookup fails
        return {
            'name': name,
            'set': set_abbr,
            'number': num_padded,
            'alternates': [],
            'quantity': 1,
        }
    return None


def merge_cards_by_printing(cards):
    """Merge rows with the same (set, number); sum quantity; preserve first-seen order."""
    buckets = {}
    order = []
    for card in cards:
        key = (card['set'], card['number'])
        qty = card.get('quantity', 1)
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 1
        if qty <= 0:
            continue
        if key not in buckets:
            buckets[key] = {
                'name': card['name'],
                'set': card['set'],
                'number': card['number'],
                'alternates': list(card.get('alternates', [])),
                'quantity': qty,
            }
            order.append(key)
        else:
            buckets[key]['quantity'] += qty
            seen = set(buckets[key]['alternates'])
            for alt in card.get('alternates', []):
                if alt not in seen:
                    buckets[key]['alternates'].append(alt)
                    seen.add(alt)
    return [buckets[k] for k in order]


def item_quantity(item):
    """Read quantity from a deck JSON item (count / quantity), default 1."""
    for key in ('count', 'quantity'):
        if key in item and item[key] is not None:
            try:
                q = int(item[key])
                return max(q, 0)
            except (TypeError, ValueError):
                break
    return 1


def parse_picklist(filepath):
    """Parse a Picklist format file and return (cards, metadata)."""
    cards = []

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Card name lines start with [ ]
        if line.startswith('[ ]'):
            # Extract card name (remove the checkbox prefix)
            name = line[3:].strip()

            # Next line should have set codes
            if i + 1 < len(lines):
                set_line = lines[i + 1].strip()
                # Skip if it's another card or section marker
                if set_line and not set_line.startswith('[ ]') and not set_line.startswith('-----'):
                    set_codes = parse_set_codes(set_line)
                    if set_codes:
                        # Prefer main sets over promos
                        primary_set, primary_num = select_primary_set(set_codes)
                        # Get unique alternate sets (excluding primary set)
                        alternate_sets = list(dict.fromkeys(
                            s for s, n in set_codes if s != primary_set
                        ))
                        cards.append({
                            'name': name,
                            'set': primary_set,
                            'number': primary_num,
                            'alternates': alternate_sets,
                            'quantity': 1,
                        })
                    i += 1  # Skip the set codes line
        i += 1

    # Picklist files don't have deck metadata - use filename as title
    metadata = {
        'title': os.path.splitext(os.path.basename(filepath))[0],
        'author': None,
        'format': None,
        'leader': None,
        'second_leader': None,
        'base': None
    }

    if metadata['format'] != 'Twin Suns':
        cards = merge_cards_by_printing(cards)

    return cards, metadata


def parse_json(filepath):
    """Parse a JSON format deck file and return (cards, metadata)."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cards = []

    # Extract metadata from file
    file_metadata = data.get('metadata', {})
    has_second_leader = 'secondleader' in data and data['secondleader']

    # Parse leader, second leader, and base for metadata
    leader_info = None
    second_leader_info = None
    base_info = None

    if 'leader' in data and data['leader'] and 'id' in data['leader']:
        leader_info = parse_card_id(data['leader']['id'])
    if has_second_leader and 'id' in data['secondleader']:
        second_leader_info = parse_card_id(data['secondleader']['id'])
    if 'base' in data and data['base'] and 'id' in data['base']:
        base_info = parse_card_id(data['base']['id'])

    # Build metadata dict
    metadata = {
        'title': file_metadata.get('name', os.path.splitext(os.path.basename(filepath))[0]),
        'author': file_metadata.get('author'),
        'format': 'Twin Suns' if has_second_leader else 'Premier',
        'leader': leader_info,
        'second_leader': second_leader_info,
        'base': base_info
    }

    # Collect all card entries from different sections
    sections = ['leader', 'secondleader', 'base', 'deck', 'sideboard']
    for section in sections:
        if section not in data:
            continue

        items = data[section]
        # Handle single item (leader/base) vs list (deck)
        if isinstance(items, dict):
            items = [items]

        for item in items:
            if not item or 'id' not in item:
                continue
            card_info = parse_card_id(item['id'])
            if card_info:
                q = item_quantity(item)
                if q <= 0:
                    continue
                entry = {**card_info, 'quantity': q}
                cards.append(entry)

    if metadata['format'] != 'Twin Suns':
        cards = merge_cards_by_printing(cards)

    return cards, metadata


# ======================================================================
# Format validation (from validate_deck_format.py)
# ======================================================================

DECK_FORMATS = {
    1: "Premier-style constructed",
    2: "Twin Suns",
}

ROTATED_PREMIER_SETS = {"SOR", "SHD", "TWI"}
PREMIER_LEGAL_MAIN_SETS = {"JTL", "LOF", "SEC", "LAW"}
TWIN_SUNS_2026_SET = "TS26"

HEROISM_ASPECT_ID = 5
VILLAINY_ASPECT_ID = 6
ALIGNMENT_ASPECT_IDS = {
    HEROISM_ASPECT_ID: "Heroism",
    VILLAINY_ASPECT_ID: "Villainy",
}

PREMIER_SUSPENDED_CARDS = {
    "Boba Fett - Collecting the Bounty",
    "Triple Dark Raid",
    "Jango Fett - Concealing the Conspiracy",
    "DJ - Blatant Thief",
    "Force Throw",
}


def is_swudb_url(input_str):
    """Check if input is a SWUDB deck URL."""
    try:
        parsed = urlparse(input_str)
        return parsed.netloc in ("swudb.com", "www.swudb.com") and "/deck/" in parsed.path
    except Exception:
        return False


def extract_deck_id(url):
    """Extract deck ID from SWUDB URL."""
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")
    if len(path_parts) >= 2 and path_parts[0] == "deck":
        return path_parts[1]
    return None


def fetch_deck_from_url(url):
    """Fetch deck JSON from SWUDB."""
    deck_id = extract_deck_id(url)
    if not deck_id:
        raise ValueError(f"Could not extract deck ID from URL: {url}")

    api_url = f"https://www.swudb.com/api/deck/{deck_id}"
    response = requests.get(api_url, timeout=30)
    if response.status_code == 404:
        raise ValueError(
            f"Deck not found at {api_url} (404). "
            "If the deck page loads in a browser, it is likely set to Private — "
            "the SWUDB API only serves Public or Unlisted decks. "
            "Open the deck on swudb.com and change visibility to Unlisted."
        )
    response.raise_for_status()
    return response.json()


def format_card_name(card_data):
    """Format a card name with title if present."""
    name = card_data.get("cardName", "")
    title = card_data.get("title", "")
    if title:
        return f"{name} - {title}"
    return name


def card_printing_label(card_data):
    """Format a card with set/number for human-readable errors."""
    card_name = format_card_name(card_data)
    set_abbr = card_data.get("defaultExpansionAbbreviation", "?")
    number = str(card_data.get("defaultCardNumber", "?")).zfill(3)
    return f"{card_name} ({set_abbr} {number})"


def extract_alignment(card_data):
    """Return Heroism/Villainy from a leader's front-side aspects, if present."""
    frontside_aspects = card_data.get("frontsideAspects") or []
    alignments = [
        ALIGNMENT_ASPECT_IDS[aspect_id]
        for aspect_id in frontside_aspects
        if aspect_id in ALIGNMENT_ASPECT_IDS
    ]
    return alignments[0] if alignments else None


def normalize_deck(data):
    """Normalize SWUDB deck payload into structures used by validation."""
    leaders = [card for card in [data.get("leader"), data.get("secondLeader")] if card]
    base = data.get("base")

    mainboard = []
    sideboard = []

    for entry in data.get("shuffledDeck", []):
        card = entry.get("card")
        if not card:
            continue

        count = entry.get("count", 0) or 0
        sideboard_count = entry.get("sideboardCount", 0) or 0

        if count > 0:
            mainboard.append(
                {
                    "card": card,
                    "quantity": count,
                    "card_id": card.get("cardId"),
                    "name": format_card_name(card),
                    "set": card.get("defaultExpansionAbbreviation", ""),
                }
            )

        if sideboard_count > 0:
            sideboard.append(
                {
                    "card": card,
                    "quantity": sideboard_count,
                    "card_id": card.get("cardId"),
                    "name": format_card_name(card),
                    "set": card.get("defaultExpansionAbbreviation", ""),
                }
            )

    return {
        "title": data.get("deckName", "Unknown Deck"),
        "url": f"https://www.swudb.com/deck/{data.get('deckId', '')}",
        "deck_format_code": data.get("deckFormat"),
        "leaders": leaders,
        "base": base,
        "mainboard": mainboard,
        "sideboard": sideboard,
    }


def detect_deck_type(deck):
    """Detect deck type using SWUDB metadata first, then structure."""
    deck_format_code = deck["deck_format_code"]
    if deck_format_code in DECK_FORMATS:
        return DECK_FORMATS[deck_format_code]

    leader_count = len(deck["leaders"])
    if leader_count == 2:
        return "Twin Suns"
    if leader_count == 1:
        return "Premier-style constructed"
    return "Unknown / malformed"


def get_premier_reprint_names():
    """Build a set of full card names available in Premier-legal main sets."""
    premier_names = set()
    for set_abbr in PREMIER_LEGAL_MAIN_SETS:
        set_df = get_swu_list(set_abbr.lower())
        if set_df is None:
            continue
        for card_name in set_df["Name"].dropna().tolist():
            premier_names.add(str(card_name).strip().lower())
    return premier_names


def validate_constructed_structure(deck, max_copies):
    """Validate the shared one-leader constructed structure."""
    reasons = []

    if len(deck["leaders"]) != 1:
        reasons.append(f"Expected exactly 1 leader; found {len(deck['leaders'])}.")

    if deck["base"] is None:
        reasons.append("Expected exactly 1 base; found 0.")

    mainboard_count = sum(card["quantity"] for card in deck["mainboard"])
    if mainboard_count < 50:
        reasons.append(f"Main deck must contain at least 50 cards; found {mainboard_count}.")

    sideboard_count = sum(card["quantity"] for card in deck["sideboard"])
    if sideboard_count > 10:
        reasons.append(f"Sideboard can contain at most 10 cards; found {sideboard_count}.")

    copies_by_card = Counter()
    for entry in deck["mainboard"]:
        key = entry["card_id"] or entry["name"]
        copies_by_card[key] += entry["quantity"]

    for entry in deck["sideboard"]:
        key = entry["card_id"] or entry["name"]
        copies_by_card[key] += entry["quantity"]

    for entry in deck["mainboard"] + deck["sideboard"]:
        key = entry["card_id"] or entry["name"]
        total = copies_by_card[key]
        if total > max_copies:
            reasons.append(
                f"{card_printing_label(entry['card'])} exceeds the {max_copies}-copy limit with {total} copies."
            )
            copies_by_card[key] = -1

    return reasons


def validate_premier(deck, premier_reprint_names):
    """Validate Premier legality."""
    reasons = validate_constructed_structure(deck, max_copies=3)

    for entry in deck["mainboard"] + deck["sideboard"]:
        card = entry["card"]
        set_abbr = entry["set"]
        name = entry["name"]
        lower_name = name.strip().lower()

        if name in PREMIER_SUSPENDED_CARDS:
            reasons.append(f"{card_printing_label(card)} is suspended in Premier.")

        if set_abbr == TWIN_SUNS_2026_SET:
            reasons.append(f"{card_printing_label(card)} is from {TWIN_SUNS_2026_SET}, which is not Premier legal.")

        if set_abbr in ROTATED_PREMIER_SETS and lower_name not in premier_reprint_names:
            reasons.append(
                f"{card_printing_label(card)} is only from a rotated set and has no sourced Premier-legal reprint."
            )

    return dedupe_reasons(reasons)


def validate_twin_suns(deck):
    """Validate Twin Suns legality; no cards are currently suspended here."""
    reasons = []

    leader_count = len(deck["leaders"])
    if leader_count != 2:
        reasons.append(f"Twin Suns requires exactly 2 leaders; found {leader_count}.")

    if deck["base"] is None:
        reasons.append("Twin Suns requires exactly 1 base; found 0.")

    mainboard_count = sum(card["quantity"] for card in deck["mainboard"])
    if mainboard_count < 80:
        reasons.append(f"Twin Suns main deck must contain at least 80 cards; found {mainboard_count}.")

    if leader_count == 2:
        leader_alignments = [extract_alignment(leader) for leader in deck["leaders"]]
        explicit = [a for a in leader_alignments if a is not None]
        if len(explicit) == 2 and explicit[0] != explicit[1]:
            reasons.append(
                "Twin Suns leaders must not mix Heroism and Villainy on their front side."
            )

    copies_by_card = Counter()
    for entry in deck["mainboard"] + deck["sideboard"]:
        key = entry["card_id"] or entry["name"]
        copies_by_card[key] += entry["quantity"]

    for entry in deck["mainboard"] + deck["sideboard"]:
        key = entry["card_id"] or entry["name"]
        total = copies_by_card[key]
        card_max = entry["card"].get("alternativeDeckMaximum")
        max_copies = card_max if isinstance(card_max, int) and card_max > 0 else 1
        if total > max_copies:
            reasons.append(
                f"{card_printing_label(entry['card'])} exceeds the Twin Suns limit of {max_copies} with {total} copies."
            )
            copies_by_card[key] = -1

    return dedupe_reasons(reasons)


def dedupe_reasons(reasons):
    """Preserve order while removing duplicate reason strings."""
    return list(dict.fromkeys(reasons))


def print_status(label, reasons):
    """Print a validation result section."""
    if reasons:
        print(f"{label}: INVALID")
        for reason in reasons:
            print(f"  - {reason}")
    else:
        print(f"{label}: VALID")


# ======================================================================
# Unified deck loader (from lib/deck_source.py)
# ======================================================================

def _identity(card_info):
    """Stable identity key for a card dict from sort_deck_by_set."""
    if not card_info:
        return None
    return (card_info["set"], str(card_info["number"]).zfill(3))


def _stub_card(name, set_abbr, number):
    """Minimal card stub compatible with card_printing_label / format_card_name."""
    return {
        "cardName": name,
        "title": "",
        "defaultExpansionAbbreviation": set_abbr,
        "defaultCardNumber": number,
    }


def _entry_from_card_info(card_info):
    """Convert a sort_deck_by_set card dict to a vdf-style mainboard entry."""
    stub = _stub_card(card_info["name"], card_info["set"], card_info["number"])
    return {
        "card": stub,
        "quantity": int(card_info.get("quantity", 1)),
        "card_id": None,
        "name": card_info["name"],
        "set": card_info["set"],
    }


def _from_url(source):
    data = fetch_deck_from_url(source)
    deck = normalize_deck(data)
    deck["metadata_complete"] = True
    deck["source"] = source
    return deck


def _separate_leaders_and_base(cards, leader_info, second_leader_info, base_info):
    """Split a flat card list into (leader_entries, base_entry, mainboard_entries).

    sort_deck_by_set's parse_json puts leaders + base in the same list as the
    deck. We pull them out by (set, number) so the normalized deck matches the
    URL-derived shape.
    """
    leader_keys = set()
    for info in (leader_info, second_leader_info):
        key = _identity(info)
        if key:
            leader_keys.add(key)
    base_key = _identity(base_info)

    leader_entries = []
    base_entry = None
    mainboard = []

    leaders_seen = set()
    base_seen = False
    for card in cards:
        key = _identity(card)
        if key in leader_keys and key not in leaders_seen:
            leader_entries.append(_stub_card(card["name"], card["set"], card["number"]))
            leaders_seen.add(key)
            continue
        if key == base_key and not base_seen:
            base_entry = _stub_card(card["name"], card["set"], card["number"])
            base_seen = True
            continue
        mainboard.append(_entry_from_card_info(card))

    # If the source declared a leader/base that wasn't in the card list, still
    # surface it via metadata so cross-deck checks see it.
    for info in (leader_info, second_leader_info):
        key = _identity(info)
        if key and key not in leaders_seen:
            leader_entries.append(_stub_card(info["name"], info["set"], info["number"]))
            leaders_seen.add(key)
    if base_key and not base_seen:
        base_entry = _stub_card(base_info["name"], base_info["set"], base_info["number"])

    return leader_entries, base_entry, mainboard


def _from_picklist(source):
    cards, metadata = parse_picklist(source)
    return _build_partial_deck(cards, metadata, source)


def _from_json(source):
    cards, metadata = parse_json(source)
    return _build_partial_deck(cards, metadata, source)


def _build_partial_deck(cards, metadata, source):
    leaders, base, mainboard = _separate_leaders_and_base(
        cards,
        metadata.get("leader"),
        metadata.get("second_leader"),
        metadata.get("base"),
    )

    declared_format = metadata.get("format")
    if declared_format == "Twin Suns":
        deck_format_code = 2
    elif declared_format == "Premier":
        deck_format_code = 1
    else:
        deck_format_code = 2 if len(leaders) == 2 else 1

    return {
        "title": metadata.get("title") or os.path.basename(source),
        "url": metadata.get("source_url", source),
        "deck_format_code": deck_format_code,
        "leaders": leaders,
        "base": base,
        "mainboard": mainboard,
        "sideboard": [],
        "metadata_complete": False,
        "source": source,
    }


# Markdown header line patterns (sort_deck_by_set.format_header output).
_LEADER_RE = re.compile(r"^\*\*Leader:\*\*\s+(.+)$")
_LEADER2_RE = re.compile(r"^\*\*Leader 2:\*\*\s+(.+)$")
_BASE_RE = re.compile(r"^\*\*Base:\*\*\s+(.+)$")
_FORMAT_RE = re.compile(r"^\*\*Format:\*\*\s+(.+)$")
_SOURCE_RE = re.compile(r"^\*\*Source:\*\*\s+\[(.+?)\]\(.+?\)\s*$")
_SET_HEADER_RE = re.compile(r"^##\s+([A-Z0-9]+)\s+\(\d+\s+CARDS\)\s*$")
_CARD_LINE_RE = re.compile(
    r"^-\s+(?P<num>\d{1,3}):\s+(?P<name>.+?)(?:\s+×(?P<qty>\d+))?(?:\s+\(also in:.*\))?\s*$"
)
_CARD_REF_RE = re.compile(r"^(?P<name>.+?)\s+\((?P<set>[A-Z0-9]+)\s+(?P<num>\d{1,3})\)\s*$")


def _parse_card_reference(value):
    """Parse 'Card Name (SET NNN)' into a card_info dict."""
    match = _CARD_REF_RE.match(value.strip())
    if not match:
        return None
    return {
        "name": match.group("name").strip(),
        "set": match.group("set").upper(),
        "number": match.group("num").zfill(3),
        "alternates": [],
        "quantity": 1,
    }


def _from_markdown(source):
    with open(source, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    title = os.path.splitext(os.path.basename(source))[0]
    declared_format = None
    source_url = None
    leader_info = None
    second_leader_info = None
    base_info = None

    cards = []
    current_set = None
    seen_separator = False

    for raw in raw_lines:
        line = raw.rstrip("\n").rstrip()
        if not line:
            continue

        if line.startswith("# ") and title == os.path.splitext(os.path.basename(source))[0]:
            # First top-level header is the title.
            title = line[2:].strip()
            continue

        if line.strip() == "---":
            seen_separator = True
            continue

        if not seen_separator:
            m = _LEADER_RE.match(line)
            if m:
                leader_info = _parse_card_reference(m.group(1))
                continue
            m = _LEADER2_RE.match(line)
            if m:
                second_leader_info = _parse_card_reference(m.group(1))
                continue
            m = _BASE_RE.match(line)
            if m:
                base_info = _parse_card_reference(m.group(1))
                continue
            m = _FORMAT_RE.match(line)
            if m:
                declared_format = m.group(1).strip()
                continue
            m = _SOURCE_RE.match(line)
            if m:
                source_url = m.group(1).strip()
                continue
            continue

        m = _SET_HEADER_RE.match(line)
        if m:
            current_set = m.group(1).upper()
            continue

        m = _CARD_LINE_RE.match(line)
        if m and current_set:
            qty_str = m.group("qty")
            qty = int(qty_str) if qty_str else 1
            cards.append({
                "name": m.group("name").strip(),
                "set": current_set,
                "number": m.group("num").zfill(3),
                "alternates": [],
                "quantity": qty,
            })

    metadata = {
        "title": title,
        "author": None,
        "format": declared_format,
        "leader": leader_info,
        "second_leader": second_leader_info,
        "base": base_info,
        "source_url": source_url,
    }
    return _build_partial_deck(cards, metadata, source)


def load_deck(source):
    """Load a deck from a SWUDB URL, .json, .txt picklist, or sorted .md file."""
    if is_swudb_url(source):
        return _from_url(source)

    if not os.path.exists(source):
        raise ValueError(f"Source not found: {source}")

    lower = source.lower()
    if lower.endswith(".json"):
        return _from_json(source)
    if lower.endswith(".md"):
        return _from_markdown(source)
    if lower.endswith(".txt"):
        return _from_picklist(source)

    raise ValueError(
        f"Unsupported source: {source}. Expected SWUDB URL or .json/.txt/.md file."
    )


def card_identity(card_data):
    """(SET, NNN) identity for a card dict from a normalized deck.

    Works for both URL-sourced cards (full SWUDB payload with
    defaultExpansionAbbreviation / defaultCardNumber) and stub cards.
    """
    set_abbr = (
        card_data.get("defaultExpansionAbbreviation")
        or card_data.get("set")
        or ""
    ).upper()
    number = card_data.get("defaultCardNumber") or card_data.get("number") or ""
    number = str(number).zfill(3) if number != "" else ""
    return (set_abbr, number)


# ======================================================================
# Trilogy logic + entry point (from trilogy_validator.py)
# ======================================================================

_LIST_LINK_RE = re.compile(r"^\s*-\s+\[(?P<name>.+?)\]\((?P<url>https?://\S+?)\)\s*$")


PREMIER_TRILOGY_LIMIT = 3
TWIN_SUNS_TRILOGY_LIMIT = 1


def _format_label(deck_type):
    if deck_type == "Twin Suns":
        return "Twin Suns Trilogy Gauntlet"
    if deck_type == "Premier-style constructed":
        return "Premier Trilogy"
    return "Trilogy"


def _label_for_card(card):
    return card_printing_label(card)


def _validate_per_deck(deck, deck_type, premier_reprint_names):
    """Run the existing per-deck validator, but skip metadata-only checks
    when the source didn't give us card metadata."""
    metadata_complete = deck.get("metadata_complete", True)

    if deck_type == "Premier-style constructed":
        if metadata_complete:
            return validate_premier(deck, premier_reprint_names), []
        reasons = dedupe_reasons(validate_constructed_structure(deck, max_copies=3))
        notes = [
            "Premier suspended-card and rotated-set checks skipped "
            "(no card metadata; re-run with SWUDB URL for full validation)."
        ]
        return reasons, notes

    if deck_type == "Twin Suns":
        if metadata_complete:
            return validate_twin_suns(deck), []
        reasons = []
        if len(deck["leaders"]) != 2:
            reasons.append(f"Twin Suns requires exactly 2 leaders; found {len(deck['leaders'])}.")
        if deck["base"] is None:
            reasons.append("Twin Suns requires exactly 1 base; found 0.")
        mainboard_count = sum(c["quantity"] for c in deck["mainboard"])
        if mainboard_count < 80:
            reasons.append(
                f"Twin Suns main deck must contain at least 80 cards; found {mainboard_count}."
            )
        copies = Counter()
        for entry in deck["mainboard"] + deck["sideboard"]:
            copies[card_identity(entry["card"])] += entry["quantity"]
        for entry in deck["mainboard"] + deck["sideboard"]:
            key = card_identity(entry["card"])
            total = copies[key]
            if total > 1:
                reasons.append(
                    f"{_label_for_card(entry['card'])} exceeds the Twin Suns "
                    f"limit of 1 with {total} copies."
                )
                copies[key] = -1
        notes = [
            "Leader alignment and alternativeDeckMaximum checks skipped "
            "(no card metadata; re-run with SWUDB URL for full validation)."
        ]
        return dedupe_reasons(reasons), notes

    return ([f"Unknown deck type: {deck_type}"], [])


def _check_distinct_leaders(decks):
    """No leader (set, number) may appear in more than one deck slot total."""
    appearances = defaultdict(list)
    for i, deck in enumerate(decks):
        for leader in deck["leaders"]:
            key = card_identity(leader)
            appearances[key].append((i, format_card_name(leader)))

    reasons = []
    for key, entries in appearances.items():
        if len(entries) > 1:
            decks_str = ", ".join(f"deck {i + 1}" for i, _ in entries)
            name = entries[0][1] or f"{key[0]} {key[1]}"
            reasons.append(f"Leader {name} appears in multiple decks: {decks_str}.")
    return reasons


def _check_distinct_bases(decks):
    appearances = defaultdict(list)
    for i, deck in enumerate(decks):
        base = deck["base"]
        if base is None:
            continue
        key = card_identity(base)
        appearances[key].append((i, format_card_name(base)))

    reasons = []
    for key, entries in appearances.items():
        if len(entries) > 1:
            decks_str = ", ".join(f"deck {i + 1}" for i, _ in entries)
            name = entries[0][1] or f"{key[0]} {key[1]}"
            reasons.append(f"Base {name} appears in multiple decks: {decks_str}.")
    return reasons


def _check_combined_copies(decks, limit):
    totals = Counter()
    per_deck = defaultdict(lambda: [0] * len(decks))
    sample_card = {}

    for i, deck in enumerate(decks):
        for entry in deck["mainboard"] + deck["sideboard"]:
            key = card_identity(entry["card"])
            totals[key] += entry["quantity"]
            per_deck[key][i] += entry["quantity"]
            sample_card.setdefault(key, entry["card"])

    reasons = []
    for key, total in totals.items():
        if total > limit:
            breakdown = ", ".join(
                f"deck {i + 1}: {qty}"
                for i, qty in enumerate(per_deck[key])
                if qty > 0
            )
            reasons.append(
                f"{_label_for_card(sample_card[key])}: {total} copies across 3 decks "
                f"(limit {limit}) [{breakdown}]."
            )
    return reasons


def _deck_size_summary(deck):
    """Return e.g. '81 Cards + 2 Leaders + 1 Base' for the detected: line."""
    main_count = sum(entry["quantity"] for entry in deck["mainboard"])
    side_count = sum(entry["quantity"] for entry in deck["sideboard"])
    leader_count = len(deck["leaders"])
    base_count = 1 if deck.get("base") else 0

    parts = [f"{main_count} Cards"]
    if side_count:
        parts.append(f"{side_count} Sideboard")
    parts.append(f"{leader_count} Leader{'s' if leader_count != 1 else ''}")
    parts.append(f"{base_count} Base")
    return " + ".join(parts)


def _print_deck_section(index, deck, deck_type, reasons, notes):
    title = deck.get("title") or f"Deck {index + 1}"
    print(f"## Deck {index + 1}: {title}")
    print(f"   source: {deck.get('source', '')}")
    print(f"   detected: {deck_type} ({_deck_size_summary(deck)})")
    for note in notes:
        print(f"   note: {note}")
    print_status(f"   {deck_type}", reasons)
    print()


def _print_trilogy_section(label, leader_reasons, base_reasons, copy_reasons):
    print(f"## {label}")
    all_reasons = leader_reasons + base_reasons + copy_reasons
    if not all_reasons:
        print("   VALID")
        return
    print("   INVALID")
    for reason in all_reasons:
        print(f"   - {reason}")


def _limit_for(deck_type):
    if deck_type == "Premier-style constructed":
        return PREMIER_TRILOGY_LIMIT
    if deck_type == "Twin Suns":
        return TWIN_SUNS_TRILOGY_LIMIT
    return None


def _emit_full_report(decks, deck_type, premier_reprint_names, limit, label):
    """Print per-deck sections + cross-deck section for an already-chosen 3.

    Returns True if any check (per-deck or cross-deck) was INVALID.
    """
    print(f"# {label}")
    print()

    invalid = False
    for i, deck in enumerate(decks):
        reasons, notes = _validate_per_deck(deck, deck_type, premier_reprint_names)
        if reasons:
            invalid = True
        _print_deck_section(i, deck, deck_type, reasons, notes)

    leader_reasons = _check_distinct_leaders(decks)
    base_reasons = _check_distinct_bases(decks)
    copy_reasons = _check_combined_copies(decks, limit=limit)
    _print_trilogy_section(label, leader_reasons, base_reasons, copy_reasons)
    print()

    if leader_reasons or base_reasons or copy_reasons:
        invalid = True
    return invalid


def _parse_lists_file(filepath):
    """Extract (name, url) entries from a markdown link list, deduped by URL."""
    entries = []
    seen = set()
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            m = _LIST_LINK_RE.match(line.rstrip())
            if not m:
                continue
            # Unescape markdown character escapes like \[ and \] in the link text.
            name = re.sub(r"\\(.)", r"\1", m.group("name").strip())
            url = m.group("url").strip()
            if url in seen:
                continue
            seen.add(url)
            entries.append((name, url))
    return entries


def _load_decks_from_entries(entries):
    """Fetch every deck in the list, reporting failures inline."""
    decks = []
    for name, url in entries:
        try:
            deck = load_deck(url)
        except (requests.RequestException, ValueError) as exc:
            print(f"  ! could not load {name} ({url}): {exc}")
            continue
        deck.setdefault("title", name)
        decks.append(deck)
    return decks


def _combo_cost(combo, limit):
    """Tuple cost: (leader-duplicate count, base-duplicate count, over-limit card count).

    Tuple comparison naturally prefers combinations with no leader/base
    duplicates, then minimizes the number of over-limit cards.
    """
    leader_keys = []
    for deck in combo:
        for leader in deck["leaders"]:
            leader_keys.append(card_identity(leader))
    leader_dups = len(leader_keys) - len(set(leader_keys))

    base_keys = [card_identity(deck["base"]) for deck in combo if deck["base"]]
    base_dups = len(base_keys) - len(set(base_keys))

    totals = Counter()
    for deck in combo:
        for entry in deck["mainboard"] + deck["sideboard"]:
            totals[card_identity(entry["card"])] += entry["quantity"]
    over_limit = sum(1 for v in totals.values() if v > limit)

    return (leader_dups, base_dups, over_limit)


def _find_best_trilogy(decks, limit):
    """Search every C(n, 3) combination; return (best_cost, best_combo)."""
    best_cost = None
    best_combo = None
    for combo in itertools.combinations(decks, 3):
        cost = _combo_cost(combo, limit)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_combo = combo
            if cost == (0, 0, 0):
                break
    return best_cost, best_combo


def _run_lists(filepath):
    entries = _parse_lists_file(filepath)
    if not entries:
        print(f"No deck links found in {filepath}.")
        raise SystemExit(1)

    print(f"# Trilogy Search: {filepath}")
    print(f"Loading {len(entries)} decks...")
    decks = _load_decks_from_entries(entries)
    if len(decks) < 3:
        print(f"Need at least 3 loadable decks; only {len(decks)} loaded.")
        raise SystemExit(1)

    # Filter to a single format (lists are organized by format).
    by_type = defaultdict(list)
    for deck in decks:
        by_type[detect_deck_type(deck)].append(deck)
    deck_type = max(by_type, key=lambda t: len(by_type[t]))
    kept = by_type[deck_type]
    dropped = [d for t, ds in by_type.items() if t != deck_type for d in ds]
    if dropped:
        print(f"Excluding {len(dropped)} deck(s) not of type '{deck_type}':")
        for deck in dropped:
            print(f"  - {deck.get('title', '?')} ({deck.get('source', '?')})")

    limit = _limit_for(deck_type)
    if limit is None:
        print(f"Cannot validate deck type: {deck_type}")
        raise SystemExit(1)
    label = _format_label(deck_type)

    premier_reprint_names = (
        get_premier_reprint_names()
        if deck_type == "Premier-style constructed"
        else set()
    )

    # Drop individually-invalid decks from the search pool — they can't be in
    # any valid Trilogy.
    valid_pool = []
    invalid_pool = []
    for deck in kept:
        reasons, _notes = _validate_per_deck(deck, deck_type, premier_reprint_names)
        if reasons:
            invalid_pool.append((deck, reasons))
        else:
            valid_pool.append(deck)

    if invalid_pool:
        print(f"Excluding {len(invalid_pool)} individually-invalid deck(s):")
        for deck, reasons in invalid_pool:
            print(f"  - {deck.get('title', '?')} ({deck.get('source', '?')}): "
                  f"{len(reasons)} {label} issue(s)")

    if len(valid_pool) < 3:
        print(f"Need at least 3 individually-valid decks; only {len(valid_pool)} qualify.")
        raise SystemExit(1)

    combo_count = math.comb(len(valid_pool), 3)
    print(f"Evaluating {combo_count} combinations of 3 from {len(valid_pool)} eligible decks...")
    print()

    best_cost, best_combo = _find_best_trilogy(valid_pool, limit)
    if best_cost == (0, 0, 0):
        print(f"## Found valid {label}")
        print()
    else:
        leader_dups, base_dups, over_limit = best_cost
        print(f"## No valid {label} found in this list")
        print(f"   Closest combination — {leader_dups} duplicate leader(s), "
              f"{base_dups} duplicate base(s), {over_limit} over-limit card(s)")
        print()

    invalid = _emit_full_report(
        list(best_combo), deck_type, premier_reprint_names, limit, label
    )
    print(f"OVERALL: {'INVALID' if invalid else 'VALID'}")
    raise SystemExit(1 if invalid else 0)


def _run_three(sources):
    decks = []
    for src in sources:
        try:
            decks.append(load_deck(src))
        except (requests.RequestException, ValueError) as exc:
            print(f"Error loading {src}: {exc}")
            raise SystemExit(1) from exc

    deck_types = [detect_deck_type(d) for d in decks]
    if len(set(deck_types)) != 1:
        print("# Trilogy: INVALID")
        print("Mismatched deck types across the three decks:")
        for i, dt in enumerate(deck_types):
            print(f"  - deck {i + 1}: {dt}")
        raise SystemExit(1)

    deck_type = deck_types[0]
    limit = _limit_for(deck_type)
    if limit is None:
        print("# Trilogy: INVALID")
        print(f"Cannot validate deck type: {deck_type}")
        raise SystemExit(1)
    label = _format_label(deck_type)

    premier_reprint_names = (
        get_premier_reprint_names()
        if deck_type == "Premier-style constructed"
        else set()
    )

    invalid = _emit_full_report(decks, deck_type, premier_reprint_names, limit, label)
    print(f"OVERALL: {'INVALID' if invalid else 'VALID'}")
    raise SystemExit(1 if invalid else 0)


def main():
    parser = argparse.ArgumentParser(
        description="Validate three SWU decks as a Trilogy build."
    )
    parser.add_argument(
        "sources",
        nargs="*",
        help="Three deck sources (SWUDB URL or path to .json/.txt/.md). "
        "Omit when using --lists.",
    )
    parser.add_argument(
        "--lists",
        metavar="FILE",
        help="Markdown file with `- [Name](URL)` lines; finds the best "
        "Trilogy combination from the listed decks.",
    )
    args = parser.parse_args()

    if args.lists and args.sources:
        parser.error("Cannot combine --lists with positional sources.")
    if args.lists:
        _run_lists(args.lists)
        return
    if len(args.sources) != 3:
        parser.error("Provide exactly 3 sources, or use --lists FILE.")
    _run_three(args.sources)


if __name__ == "__main__":
    main()
