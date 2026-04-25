#!/usr/bin/env python3
"""Validate three SWU decks as a Trilogy build.

Premier Trilogy: max 3 copies of any card across all 3 decks combined,
distinct leaders, distinct bases, all decks Premier-legal.

Twin Suns Trilogy Gauntlet (community format): max 1 copy of any card
across all 3 decks combined, distinct leaders, distinct bases, all decks
Twin Suns-legal.

Sources may be SWUDB URLs, .json deck exports, .txt picklists, or sorted
.md files produced by sort_deck_by_set.py. Non-URL sources can't supply
aspect / alternativeDeckMaximum / suspended-name data, so checks that
need that metadata are skipped with a printed note.
"""

import argparse
import itertools
import math
import re
from collections import Counter, defaultdict

import requests

import validate_deck_format as vdf
from lib.deck_source import card_identity, load_deck


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
    return vdf.card_printing_label(card)


def _validate_per_deck(deck, deck_type, premier_reprint_names):
    """Run the existing per-deck validator, but skip metadata-only checks
    when the source didn't give us card metadata."""
    metadata_complete = deck.get("metadata_complete", True)

    if deck_type == "Premier-style constructed":
        if metadata_complete:
            return vdf.validate_premier(deck, premier_reprint_names), []
        reasons = vdf.dedupe_reasons(vdf.validate_constructed_structure(deck, max_copies=3))
        notes = [
            "Premier suspended-card and rotated-set checks skipped "
            "(no card metadata; re-run with SWUDB URL for full validation)."
        ]
        return reasons, notes

    if deck_type == "Twin Suns":
        if metadata_complete:
            return vdf.validate_twin_suns(deck), []
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
        return vdf.dedupe_reasons(reasons), notes

    return ([f"Unknown deck type: {deck_type}"], [])


def _check_distinct_leaders(decks):
    """No leader (set, number) may appear in more than one deck slot total."""
    appearances = defaultdict(list)
    for i, deck in enumerate(decks):
        for leader in deck["leaders"]:
            key = card_identity(leader)
            appearances[key].append((i, vdf.format_card_name(leader)))

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
        appearances[key].append((i, vdf.format_card_name(base)))

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


def _print_deck_section(index, deck, deck_type, reasons, notes):
    title = deck.get("title") or f"Deck {index + 1}"
    print(f"## Deck {index + 1}: {title}")
    print(f"   source: {deck.get('source', '')}")
    print(f"   detected: {deck_type}")
    for note in notes:
        print(f"   note: {note}")
    vdf.print_status(f"   {deck_type}", reasons)
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
        by_type[vdf.detect_deck_type(deck)].append(deck)
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
        vdf.get_premier_reprint_names()
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

    deck_types = [vdf.detect_deck_type(d) for d in decks]
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
        vdf.get_premier_reprint_names()
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
