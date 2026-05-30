"""Build card_data/ts26_decks.json from the "TS Pre-Con Deck Breakdown" sheet.

The SWUDB API has no field telling you which pre-constructed Twin Suns 2026
deck a TS26 card belongs to, so that mapping is sourced manually from the
community "TS Pre-Con Deck Breakdown" spreadsheet and committed here.

Input: a CSV export of the sheet's "All Cards" tab with columns:
    Deck, Set, Number, Card Name, Type, Arena, Notes, is TS26 (boolean)

Only rows whose Set is TS26 are mapped (those are the cards that exist solely
in the pre-cons and not in any collectable set). Each TS26 card number maps to
the list of decks it appears in, since some TS26 cards are shared across
multiple of the four decks while leaders/bases are exclusive to one.

Usage:
    uv run python build_ts26_decks.py /path/to/all_cards.csv
"""

import csv
import json
import os
import sys

OUTPUT_PATH = os.path.join("card_data", "ts26_decks.json")


def build_mapping(csv_path):
    csv.field_size_limit(10**7)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    cards = {}
    deck_order = []
    for r in rows[1:]:
        if len(r) < 5:
            continue
        deck = r[0].strip()
        set_abbr = r[1].strip()
        number = r[2].strip()
        name = r[3].strip()
        card_type = r[4].strip()
        if set_abbr.upper() != "TS26" or not number or not deck:
            continue
        number = number.zfill(3)
        if deck not in deck_order:
            deck_order.append(deck)
        entry = cards.setdefault(
            number, {"name": name, "type": card_type, "decks": []}
        )
        if deck not in entry["decks"]:
            entry["decks"].append(deck)

    return {"decks": deck_order, "cards": cards}


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python build_ts26_decks.py <all_cards.csv>")
        sys.exit(1)

    data = build_mapping(sys.argv[1])
    cards = data["cards"]
    ordered = {
        "decks": data["decks"],
        "cards": {num: cards[num] for num in sorted(cards)},
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {OUTPUT_PATH}: {len(cards)} TS26 cards across {len(data['decks'])} decks")
    for deck in data["decks"]:
        count = sum(1 for c in cards.values() if deck in c["decks"])
        print(f"  {deck}: {count} TS26-exclusive cards")


if __name__ == "__main__":
    main()
