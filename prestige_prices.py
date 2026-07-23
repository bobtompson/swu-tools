"""Show TCGplayer prices for prestige variants (normal and foil).

Prestige printings exist from JTL onward. Each prestige card has three
tiers on TCGplayer — Prestige, Prestige Foil, and Serialized — this
script prices the first two; Serialized is deliberately excluded (the
prices are extreme and not useful for planning).

With --mark-sheet it also puts a bold border on the column E cell of
every card that has a prestige printing, on each set's inventory tab
(column E is the hand-entered variant-ownership column: P1 non-foil
prestige, P2 foil prestige, P3(serial) serialized, S showcase).

Usage:
    uv run python prestige_prices.py                 # all main sets, console only
    uv run python prestige_prices.py law ash         # specific sets
    uv run python prestige_prices.py --mark-sheet    # also mark column E cells
"""

import sys

import lib.swudb as swudb
import lib.tcgcsv as tcgcsv
from main import get_doc_sheet
from showcase_prices import format_money, original_card_number

PRESTIGE_BORDER = {
    'borders': {side: {'style': 'SOLID_THICK'}
                for side in ('top', 'bottom', 'left', 'right')}
}


def collect_prestige(set_names):
    """Fetch prestige normal+foil prices per set, merged per card.

    Returns {set_name: [{'original': '039', 'name': ...,
                         'prestige': entry|None, 'foil': entry|None}]}
    sorted by original card number. Sets without prestige products
    (pre-JTL) are skipped with a note.
    """
    results = {}
    for set_name in set_names:
        set_name = set_name.lower()
        if set_name not in tcgcsv.GROUPS:
            print(f'Skipping {set_name.upper()}: no TCGplayer group known')
            continue
        prestige = tcgcsv.get_variant_list(set_name, '(Prestige)')
        foil = tcgcsv.get_variant_list(set_name, '(Prestige Foil)')
        if prestige is None or foil is None:
            continue
        if not prestige and not foil:
            print(f'Skipping {set_name.upper()}: no prestige cards found')
            continue

        set_df = swudb.get_swu_list(set_name)
        variants = prestige + foil
        for entry in variants:
            entry['original'] = original_card_number(set_df, entry['number'])
        if any(not entry['original'] for entry in variants):
            # Cache may predate the set's variant data — refresh once
            set_df = swudb.get_swu_list(set_name, force_refresh=True)
            for entry in variants:
                entry['original'] = original_card_number(set_df, entry['number'])

        merged = {}
        for tier, entries in (('prestige', prestige), ('foil', foil)):
            for entry in entries:
                key = entry['original'] or entry['number']
                card = merged.setdefault(
                    key, {'original': entry['original'], 'name': entry['name'],
                          'prestige': None, 'foil': None})
                card[tier] = entry
        results[set_name] = sorted(merged.values(),
                                   key=lambda c: c['original'] or '999')
    return results


def print_prestige(prestige_by_set):
    for set_name, cards in prestige_by_set.items():
        market_total = sum((c['prestige']['market'] or 0 if c['prestige'] else 0)
                           + (c['foil']['market'] or 0 if c['foil'] else 0)
                           for c in cards)
        print(f'\n=== {set_name.upper()} — {tcgcsv.get_set_display_name(set_name)} '
              f'({len(cards)} prestige cards) ===')
        for c in cards:
            original = f"{c['original']}" if c['original'] else '???'

            def tier(entry):
                if entry is None:
                    return '      —   '
                return f"{format_money(entry['market']):>10}"

            print(f"  {original}  {c['name']:<45.45}  "
                  f"prestige {tier(c['prestige'])}  "
                  f"foil {tier(c['foil'])}")
        print(f'  set total (both tiers): market {format_money(market_total)}')


def contiguous_ranges(numbers):
    """Merge sorted ints into (start, end) runs: [3,4,5,9] -> [(3,5),(9,9)]."""
    runs = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return [(a, b) for a, b in runs]


def mark_sheet(set_name, cards):
    """Bold-border the column E cells of cards with a prestige printing."""
    rows = sorted({int(c['original']) + 2 for c in cards if c['original']})
    if not rows:
        print(f'  {set_name.upper()}: no resolvable card numbers, tab not marked')
        return
    sheet = get_doc_sheet(set_name.upper())
    formats = [{'range': f'E{a}:E{b}', 'format': PRESTIGE_BORDER}
               for a, b in contiguous_ranges(rows)]
    sheet.batch_format(formats)
    print(f'  {set_name.upper()}: marked {len(rows)} column E cells '
          f'({len(formats)} ranges)')


if __name__ == '__main__':
    args = sys.argv[1:]
    with_mark = '--mark-sheet' in args
    if with_mark:
        args.remove('--mark-sheet')

    set_names = args or [s for s in swudb.MAIN_SETS if s in tcgcsv.GROUPS]
    prestige_by_set = collect_prestige(set_names)
    if not prestige_by_set:
        print('No prestige data found.')
        sys.exit(1)

    print_prestige(prestige_by_set)
    if with_mark:
        print('\nMarking prestige cards on inventory tabs (column E borders):')
        for set_name, cards in prestige_by_set.items():
            mark_sheet(set_name, cards)
