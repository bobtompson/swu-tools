"""Show TCGplayer prices for sealed products: booster displays and Spotlight Decks.

Prices come from tcgcsv.com (see lib/tcgcsv.py). Each set has a regular
booster display; from JTL onward there's also a Carbonite Edition display
and two Spotlight Decks (sold singly or as a Pair). The 6-deck Spotlight
Deck Display case is not tracked. Missing products show n/a.

Usage:
    uv run python sealed_prices.py                 # every main set
    uv run python sealed_prices.py law ash         # specific sets
    uv run python sealed_prices.py --update-sheet  # also update the Sealed tab

Sealed tab layout: B1/C1 'Prices Updated:' stamp, headers in row 2, one
row per set from row 3 (columns A-O, see HEADERS; column G is a blank
spacer between the displays and the Spotlight Decks). Spotlight decks are
listed in TCGplayer productId order, named by leader. Rows are matched by
the Set column, so row order and anything in columns P+ are left alone;
new sets append.
"""

import sys
from datetime import datetime

import lib.swudb as swudb
import lib.tcgcsv as tcgcsv

SHEET_TAB = 'Sealed'
HEADERS = ['Set', 'Set Name',
           'Booster Market', 'Booster Low',
           'Carbonite Market', 'Carbonite Low',
           '',  # G: spacer column
           'Spotlight Deck 1', 'Deck 1 Market', 'Deck 1 Low',
           'Spotlight Deck 2', 'Deck 2 Market', 'Deck 2 Low',
           'Deck Pair Market', 'Deck Pair Low']
LAST_COLUMN = 'O'
FIRST_DATA_ROW = 3


def format_price(value):
    return f'${value:,.2f}' if value is not None else 'n/a'


def collect_prices(set_names):
    """Return one row dict per set with its sealed products."""
    rows = []
    for set_name in set_names:
        sealed = tcgcsv.get_sealed_products(set_name)
        if sealed is None:
            print(f"Skipping {set_name.upper()}: no TCGplayer data")
            continue
        decks = sealed['spotlight_decks']
        if len(decks) > 2:
            print(f"Warning: {set_name.upper()} has {len(decks)} Spotlight "
                  f"Decks; only the first two are shown")
        rows.append({
            'set': set_name.upper(),
            'set_name': tcgcsv.get_set_display_name(set_name),
            'booster': sealed.get('booster'),
            'carbonite': sealed.get('carbonite'),
            'decks': (decks + [None, None])[:2],
            'pair': sealed.get('spotlight_pair'),
        })
    return rows


def price_cells(entry):
    """(market, low) for an entry, None when the product doesn't exist."""
    entry = entry or {}
    return entry.get('market'), entry.get('low')


def print_prices(rows):
    print('Booster Displays')
    print(f"{'Set':<5} {'Set Name':<26} {'Booster Mkt':>11} {'Low':>9}"
          f"   {'Carbonite Mkt':>13} {'Low':>9}")
    print('-' * 80)
    for row in rows:
        booster = price_cells(row['booster'])
        carbonite = price_cells(row['carbonite'])
        print(f"{row['set']:<5} {row['set_name']:<26} "
              f"{format_price(booster[0]):>11} {format_price(booster[1]):>9}   "
              f"{format_price(carbonite[0]):>13} {format_price(carbonite[1]):>9}")

    spotlight_rows = [r for r in rows if any(r['decks']) or r['pair']]
    if not spotlight_rows:
        return
    print('\nSpotlight Decks')
    print(f"{'Set':<5} {'Deck':<32} {'Market':>9} {'Low':>9}")
    print('-' * 58)
    for row in spotlight_rows:
        entries = [(deck['leader'], deck) for deck in row['decks'] if deck]
        if row['pair']:
            entries.append(('Pair (both decks)', row['pair']))
        for i, (label, entry) in enumerate(entries):
            market, low = price_cells(entry)
            set_label = row['set'] if i == 0 else ''
            print(f"{set_label:<5} {label:<32} "
                  f"{format_price(market):>9} {format_price(low):>9}")


def sheet_values(row):
    """Sheet cells for one set; missing products/prices are left blank."""
    def prices(entry):
        return ['' if v is None else v for v in price_cells(entry)]

    values = [row['set'], row['set_name'],
              *prices(row['booster']), *prices(row['carbonite']), '']
    for deck in row['decks']:
        values += [deck['leader'] if deck else '', *prices(deck)]
    values += prices(row['pair'])
    return values


def update_sheet(rows):
    """Upsert each set's row on the Sealed tab, keyed by column A."""
    from main import get_doc_sheet

    sheet = get_doc_sheet(SHEET_TAB)
    existing = sheet.col_values(1)[FIRST_DATA_ROW - 1:]
    row_by_set = {value.strip().upper(): FIRST_DATA_ROW + i
                  for i, value in enumerate(existing) if value.strip()}
    next_row = FIRST_DATA_ROW + len(existing)

    updates = []
    added = 0
    for row in rows:
        sheet_row = row_by_set.get(row['set'])
        if sheet_row is None:
            sheet_row = next_row
            next_row += 1
            added += 1
        updates.append({'range': f'A{sheet_row}:{LAST_COLUMN}{sheet_row}',
                        'values': [sheet_values(row)]})

    updates.append({'range': 'B1:C1', 'values': [
        ['Prices Updated:', datetime.now().strftime('%Y-%m-%d %H:%M')]]})
    updates.append({'range': f'A2:{LAST_COLUMN}2', 'values': [HEADERS]})
    sheet.batch_update(updates)

    last_row = max(next_row - 1, FIRST_DATA_ROW)
    currency = {'numberFormat': {'type': 'CURRENCY', 'pattern': '$0.00'}}
    sheet.batch_format([
        {'range': cols, 'format': currency}
        for cols in (f'C{FIRST_DATA_ROW}:F{last_row}',
                     f'I{FIRST_DATA_ROW}:J{last_row}',
                     f'L{FIRST_DATA_ROW}:O{last_row}')
    ] + [{'range': f'A2:{LAST_COLUMN}2',
          'format': {'textFormat': {'bold': True}}}])
    print(f"\nUpdated {len(rows) - added} and added {added} rows on the "
          f"{SHEET_TAB} tab")


def main(argv):
    update = '--update-sheet' in argv
    args = [a.lower() for a in argv if not a.startswith('--')]

    invalid = [a for a in args if a not in swudb.MAIN_SETS]
    if invalid:
        print(f"Unknown set(s): {', '.join(invalid)}. "
              f"Main sets: {', '.join(swudb.MAIN_SETS)}")
        return 1

    rows = collect_prices(args or swudb.MAIN_SETS)
    print_prices(rows)
    if update and rows:
        update_sheet(rows)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
