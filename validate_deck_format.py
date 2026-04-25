#!/usr/bin/env python3
"""
Validate a SWUDB deck for Premier, Eternal, and Twin Suns legality.
"""

import argparse
from collections import Counter
from urllib.parse import urlparse

import requests

import lib.swudb as swudb

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
        set_df = swudb.get_swu_list(set_abbr.lower())
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


def validate_eternal(deck):
    """Validate Eternal legality; all released cards are currently allowed."""
    return dedupe_reasons(validate_constructed_structure(deck, max_copies=3))


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


def main():
    parser = argparse.ArgumentParser(
        description="Validate a SWUDB deck for Premier, Eternal, and Twin Suns legality."
    )
    parser.add_argument("url", help="SWUDB deck URL")
    args = parser.parse_args()

    if not is_swudb_url(args.url):
        print(f"Error: Invalid SWUDB deck URL: {args.url}")
        raise SystemExit(1)

    try:
        deck_data = fetch_deck_from_url(args.url)
    except requests.RequestException as exc:
        print(f"Error fetching deck: {exc}")
        raise SystemExit(1) from exc
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    deck = normalize_deck(deck_data)
    detected_deck_type = detect_deck_type(deck)
    premier_reprint_names = get_premier_reprint_names()

    premier_reasons = validate_premier(deck, premier_reprint_names)
    eternal_reasons = validate_eternal(deck)
    twin_suns_reasons = validate_twin_suns(deck)

    print(f"# {deck['title']}")
    print(f"URL: {args.url}")
    print(f"Detected deck type: {detected_deck_type}")
    print()
    print_status("Premier", premier_reasons)
    print()
    print_status("Eternal", eternal_reasons)
    print()
    print_status("Twin Suns", twin_suns_reasons)


if __name__ == "__main__":
    main()
