"""List the cards in a set that are reprints from an older set.

A reprint is a numbered card whose Name + Subtitle was already printed in a
set released earlier (main and sub sets only — promo printings don't count).

With --mark-sheet it also puts a bold red border on the column B (card name)
cell of every reprint on each set's inventory tab, the same way
prestige_prices.py --mark-sheet outlines column E.

Usage:
    uv run python mark_reprints.py                  # every set, console only
    uv run python mark_reprints.py ic27 law         # specific sets
    uv run python mark_reprints.py --mark-sheet     # also outline column B cells
"""

import argparse
import sys

import lib.swudb as swudb
from prestige_prices import contiguous_ranges
from promo_prices import build_original_index, card_key, load_set_rows

RED = {'red': 1, 'green': 0, 'blue': 0}
REPRINT_BORDER = {
    'borders': {side: {'style': 'SOLID_THICK', 'color': RED}
                for side in ('top', 'bottom', 'left', 'right')}
}


def numbered_cards(set_name):
    """The set's base printings as {int number: card} — tokens ('T01') are
    skipped and the lowest-numbered row wins over any duplicate."""
    info = next((s for s in swudb.get_sets_catalog()
                 if s.get('setId') == set_name.upper()), {})
    card_count = info.get('numberCards')
    cards = {}
    for card in load_set_rows(set_name):
        number = str(card.get('Number', ''))
        if not number.isdigit():
            continue
        if card_count and int(number) > card_count:
            continue  # variants are numbered above the set's card count
        cards.setdefault(int(number), card)
    return cards


def find_reprints(set_name, index):
    """[(number, card, 'SET NNN' original)] for cards first printed elsewhere.

    Bases filled in from swudb.com have no Subtitle (see lib/swudb.py), so a
    base with a blank subtitle is matched on its name alone.
    """
    set_id = set_name.upper()
    by_name = {}
    for (name, _subtitle), original in index.items():
        by_name.setdefault(name, original)

    reprints = []
    for number, card in sorted(numbered_cards(set_name).items()):
        key = card_key(card)
        original = index.get(key)
        if original is None and card.get('Type') == 'Base' and not key[1]:
            original = by_name.get(key[0])
        if original and original.split()[0] != set_id:
            reprints.append((number, card, original))
    return reprints


def print_reprints(set_name, reprints, total):
    print(f'\n=== {set_name.upper()} — {len(reprints)} reprint(s) of {total} cards ===')
    for number, card, original in reprints:
        _, subtitle = card_key(card)
        title = card.get('Name', '')
        if subtitle:
            title += f" - {card['Subtitle']}"
        print(f'  {number:03d} {title}  (first printed {original})')


def mark_sheet(sheet, set_name, reprints):
    """Bold red border on the column B cells of the reprinted cards."""
    rows = [number + 2 for number, _card, _original in reprints]
    if not rows:
        print(f'  {set_name.upper()}: no reprints, tab not marked')
        return
    formats = [{'range': f'B{a}:B{b}', 'format': REPRINT_BORDER}
               for a, b in contiguous_ranges(rows)]
    sheet.batch_format(formats)
    print(f'  {set_name.upper()}: outlined {len(rows)} column B cells '
          f'({len(formats)} ranges)')


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sets', nargs='*', help='set abbreviations (default: every set)')
    parser.add_argument('--mark-sheet', action='store_true',
                        help="red-border column B for reprints on each set's tab")
    args = parser.parse_args()

    sets = [s.lower() for s in args.sets] or list(swudb.VALID_SETS)
    unknown = [s for s in sets if s not in swudb.VALID_SETS]
    if unknown:
        print(f"Unknown set(s): {', '.join(unknown)}. "
              f"Valid sets: {', '.join(swudb.VALID_SETS)}")
        return 2

    index = build_original_index()
    reprints_by_set = {}
    for set_name in sets:
        reprints_by_set[set_name] = find_reprints(set_name, index)
        print_reprints(set_name, reprints_by_set[set_name], len(numbered_cards(set_name)))

    if args.mark_sheet:
        import main as inventory  # deferred: Google auth only when marking

        print('\nOutlining reprints on inventory tabs (column B borders):')
        tabs = {ws.title: ws for ws in inventory.get_spreadsheet().worksheets()}
        for set_name, reprints in reprints_by_set.items():
            sheet = tabs.get(set_name.upper())
            if sheet is None:
                print(f'  {set_name.upper()}: no tab in the spreadsheet, skipped')
                continue
            mark_sheet(sheet, set_name, reprints)
    return 0


if __name__ == '__main__':
    sys.exit(main())
