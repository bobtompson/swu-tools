"""Write TCGplayer prices onto the inventory spreadsheet for a set.

Fills columns H (Market) and I (Low) on the set's tab, aligned with the
card rows that main.py maintains. Prices come from tcgcsv.com (see
lib/tcgcsv.py) and use the Normal printing of each card.

Usage:
    uv run python update_prices.py ash
    uv run python update_prices.py law sec   # multiple sets in one run
"""

import sys
from datetime import datetime

import lib.swudb as swudb
import lib.tcgcsv as tcgcsv
from main import get_doc_sheet


def update_prices(set_name):
    """Update the Market/Low price columns for one set's tab."""
    set_name = set_name.lower()
    if set_name not in swudb.VALID_SETS:
        print(f"Invalid set: {set_name}. Valid sets: {', '.join(swudb.VALID_SETS)}")
        return False

    price_map = tcgcsv.get_price_map(set_name)
    if price_map is None:
        print(f"Failed to get price data for {set_name.upper()}, aborting update.")
        return False

    sheet = get_doc_sheet(set_name.upper())
    card_count = int(sheet.cell(1, 8).value)
    print(f"Card count: {card_count} for {set_name.upper()}")

    rows = []
    missing = []
    for num in range(1, card_count + 1):
        card_num = f'{num:03d}'
        entry = price_map.get(card_num)
        if entry is None:
            rows.append(['', ''])
            missing.append(card_num)
        else:
            rows.append([entry['market'], entry['low']])

    last_row = card_count + 2  # data starts at row 3
    sheet.update([['Market', 'Low']], 'H2:I2')
    sheet.update(rows, f'H3:I{last_row}')
    sheet.format(f'H3:I{last_row}',
                 {'numberFormat': {'type': 'CURRENCY', 'pattern': '$0.00'}})
    # Per-set price freshness stamp; J1/K1 follow the F1/G1 label/value
    # pattern (I1 holds the "Card Count" label for H1).
    sheet.update([['Prices Updated:', datetime.now().strftime('%Y-%m-%d %H:%M')]],
                 'J1:K1')

    print(f"Wrote prices for {card_count - len(missing)}/{card_count} cards "
          f"to {set_name.upper()} (H3:I{last_row})")
    if missing:
        print(f"  {len(missing)} cards had no TCGplayer price (left blank):")
        df = swudb.get_swu_list(set_name)
        for card_num in missing:
            name = swudb.get_card_name(df, card_num) or 'Unknown'
            print(f"    {set_name.upper()} {card_num} - {name}")
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    for arg in sys.argv[1:]:
        update_prices(arg)
