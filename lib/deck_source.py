"""Unified deck loader: SWUDB URLs, .json, .txt picklists, and sorted .md files.

Returns a normalized deck dict with the same shape as
``validate_deck_format.normalize_deck`` so the existing per-deck validators
can consume any input type. Non-URL sources have ``metadata_complete=False``
and minimal card stubs (no aspects / no ``alternativeDeckMaximum``).
"""

import os
import re

from sort_deck_by_set import parse_picklist, parse_json
import validate_deck_format as vdf


def _identity(card_info):
    """Stable identity key for a card dict from sort_deck_by_set."""
    if not card_info:
        return None
    return (card_info["set"], str(card_info["number"]).zfill(3))


def _stub_card(name, set_abbr, number):
    """Minimal card stub compatible with vdf.card_printing_label / format_card_name."""
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
    data = vdf.fetch_deck_from_url(source)
    deck = vdf.normalize_deck(data)
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
    if vdf.is_swudb_url(source):
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
