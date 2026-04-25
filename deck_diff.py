#!/usr/bin/env python3
"""Show a GitHub-style diff between two SWU decks.

Identity is (set, number) — a card with the same name in a different set
prints as one removal + one addition (the right behaviour for "what to
pull from binders"). Sources may be SWUDB URLs, .json deck exports, .txt
picklists, or sorted .md files produced by sort_deck_by_set.py.
"""

import argparse

import requests

import validate_deck_format as vdf
from lib.deck_source import card_identity, load_deck


def _section_map(entries):
    """(set, number) -> {'qty': int, 'card': payload, 'name': str} for one section."""
    out = {}
    for entry in entries:
        card = entry["card"]
        key = card_identity(card)
        if key in out:
            out[key]["qty"] += entry["quantity"]
        else:
            out[key] = {
                "qty": entry["quantity"],
                "card": card,
                "name": vdf.format_card_name(card),
            }
    return out


def _leaders_map(leaders):
    out = {}
    for leader in leaders:
        key = card_identity(leader)
        out[key] = {
            "qty": 1,
            "card": leader,
            "name": vdf.format_card_name(leader),
        }
    return out


def _base_map(base):
    if base is None:
        return {}
    return {
        card_identity(base): {
            "qty": 1,
            "card": base,
            "name": vdf.format_card_name(base),
        }
    }


def _diff_section(old_map, new_map):
    """Yield ('-' or '+', qty, label) tuples for the differences in one section."""
    keys = sorted(set(old_map) | set(new_map))
    lines = []
    added = removed = 0
    for key in keys:
        old_entry = old_map.get(key)
        new_entry = new_map.get(key)
        old_qty = old_entry["qty"] if old_entry else 0
        new_qty = new_entry["qty"] if new_entry else 0
        if old_qty == new_qty:
            continue
        card = (new_entry or old_entry)["card"]
        label = vdf.card_printing_label(card)
        if old_qty > 0:
            lines.append(("-", old_qty, label))
            removed += old_qty
        if new_qty > 0:
            lines.append(("+", new_qty, label))
            added += new_qty
    return lines, added, removed


def _print_section(title, lines):
    if not lines:
        return
    print(f"## {title}")
    for sign, qty, label in lines:
        print(f"{sign} {qty}x {label}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Show a GitHub-style diff between two SWU decks."
    )
    parser.add_argument("old", help="Old deck: SWUDB URL or path to .json/.txt/.md")
    parser.add_argument("new", help="New deck: SWUDB URL or path to .json/.txt/.md")
    args = parser.parse_args()

    try:
        old_deck = load_deck(args.old)
        new_deck = load_deck(args.new)
    except (requests.RequestException, ValueError) as exc:
        print(f"Error loading deck: {exc}")
        raise SystemExit(1) from exc

    print(f"# Deck Diff: {old_deck.get('title', args.old)} → {new_deck.get('title', args.new)}")
    print(f"  old: {old_deck.get('source', args.old)}")
    print(f"  new: {new_deck.get('source', args.new)}")
    print()

    sections = [
        ("Leaders", _leaders_map(old_deck["leaders"]), _leaders_map(new_deck["leaders"])),
        ("Base", _base_map(old_deck["base"]), _base_map(new_deck["base"])),
    ]

    # Markdown / picklist sources flatten sideboard into the main deck. If either
    # side lacks full metadata, fold sideboards into mainboards for the diff so
    # we don't report phantom sideboard moves that are really just input-format
    # differences.
    fold_sideboard = not (
        old_deck.get("metadata_complete", False) and new_deck.get("metadata_complete", False)
    )
    if fold_sideboard:
        sections.append((
            "Main Deck",
            _section_map(old_deck["mainboard"] + old_deck["sideboard"]),
            _section_map(new_deck["mainboard"] + new_deck["sideboard"]),
        ))
    else:
        sections.append((
            "Main Deck",
            _section_map(old_deck["mainboard"]),
            _section_map(new_deck["mainboard"]),
        ))
        sections.append((
            "Sideboard",
            _section_map(old_deck["sideboard"]),
            _section_map(new_deck["sideboard"]),
        ))

    total_added = 0
    total_removed = 0
    any_changes = False
    for title, old_map, new_map in sections:
        lines, added, removed = _diff_section(old_map, new_map)
        if lines:
            any_changes = True
        _print_section(title, lines)
        total_added += added
        total_removed += removed

    if not any_changes:
        print("No changes between decks.")
        return

    print(f"Summary: +{total_added}, -{total_removed}")


if __name__ == "__main__":
    main()
