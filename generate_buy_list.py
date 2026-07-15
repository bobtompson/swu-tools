"""Generate a priced buy list of cards missing from a full playset.

Reads the inventory spreadsheet (the same tabs main.py maintains), finds
every card with fewer than PLAYSET copies, prices the missing copies via
TCGplayer (tcgcsv.com), and writes a text buy list.

Leaders and bases are skipped by default (you rarely need a playset of
those); pass --all to include them. Blank Count cells are ignored — blank
means "not tracked", so a wanted card owned zero times gets an explicit 0.

Usage:
    uv run python generate_buy_list.py               # every set tab found
    uv run python generate_buy_list.py law ash       # specific sets
    uv run python generate_buy_list.py --all         # include leaders/bases
    uv run python generate_buy_list.py -o wants.txt  # custom output file
"""

import datetime as dt
import sys

import lib.swudb as swudb
import lib.tcgcsv as tcgcsv
from main import get_spreadsheet

PLAYSET = 3
DEFAULT_OUTPUT = 'buy_list.txt'

# Row/column layout of each set tab (see main.py / CLAUDE.md)
HEADER_ROWS = 2  # data starts at row 3
COL_NUMBER, COL_NAME, COL_COUNT, COL_RARITY = 0, 1, 2, 3


def parse_count(raw):
    """Owned-copy count from a sheet cell, or None when blank/junk.

    A blank Count cell means the card isn't tracked (not needed) — an
    explicit 0 is entered when a card is owned zero times but wanted.
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def leader_base_numbers(set_name):
    """3-digit card numbers of the Leaders and Bases in a set.

    Uses the cached swu-db card data (fetched on first miss). Returns an
    empty set if the data is unavailable, so filtering degrades to a no-op.
    """
    set_df = swudb.get_swu_list(set_name)
    if set_df is None or 'Type' not in set_df.columns:
        return set()
    mask = set_df['Type'].isin(('Leader', 'Base'))
    return set(set_df.loc[mask, 'Number'].astype(str).str.zfill(3))


def missing_cards_for_sheet(sheet, skip_numbers=frozenset()):
    """Scan one set tab and return rows for cards short of a playset.

    Rows with a blank Count cell are ignored (blank = not tracked; an
    explicit 0 marks a wanted card that's owned zero times). Rows whose
    3-digit number is in skip_numbers (e.g. leaders/bases) are excluded.
    Returns (missing, blanks, skipped): missing is a list of dicts
    {number, name, rarity, need}; blanks is how many rows were ignored for
    a blank count; skipped is how many short-of-playset rows were excluded
    via skip_numbers.
    """
    values = sheet.get_all_values()
    card_count = int(values[0][7])  # H1

    missing = []
    blanks = 0
    skipped = 0
    for row in values[HEADER_ROWS:HEADER_ROWS + card_count]:
        count = parse_count(row[COL_COUNT])
        if count is None:
            blanks += 1
            continue
        need = PLAYSET - count
        if need > 0:
            if row[COL_NUMBER].zfill(3) in skip_numbers:
                skipped += 1
                continue
            missing.append({
                'number': row[COL_NUMBER],
                'name': row[COL_NAME],
                'rarity': row[COL_RARITY],
                'need': need,
            })
    return missing, blanks, skipped


def format_money(value):
    return f'${value:,.2f}' if value is not None else '   n/a'


def build_set_section(set_name, missing, price_map, blanks=0):
    """Format one set's buy-list section. Returns (lines, market_total, low_total)."""
    lines = [f'=== {set_name.upper()} — {tcgcsv.get_set_display_name(set_name)} ===']
    if blanks:
        lines.append(f'  note: {blanks} cards with a blank count were ignored '
                     f'(blank = not tracked)')
    market_total = low_total = 0.0

    for card in missing:
        entry = (price_map or {}).get(card['number'].zfill(3))
        market = entry['market'] if entry else None
        low = entry['low'] if entry else None
        if market is not None:
            market_total += card['need'] * market
        if low is not None:
            low_total += card['need'] * low
        lines.append(
            f"  {card['need']}x {card['number']:>3} "
            f"{card['name']:<40.40} ({card['rarity'] or '?'})  "
            f"market {format_money(market):>8}  low {format_money(low):>8}"
        )

    copies = sum(c['need'] for c in missing)
    lines.append(f'  subtotal: {len(missing)} cards / {copies} copies — '
                 f'market {format_money(market_total)}, low {format_money(low_total)}')
    lines.append('')
    return lines, market_total, low_total


def generate_buy_list(set_names, output_path=DEFAULT_OUTPUT, include_leaders_bases=False):
    spreadsheet = get_spreadsheet()

    if not set_names:
        # Every tab whose title is a known set, in release order
        tab_titles = {ws.title for ws in spreadsheet.worksheets()}
        set_names = [s for s in swudb.VALID_SETS if s.upper() in tab_titles]
        if not set_names:
            print('No set tabs found in the spreadsheet.')
            return

    today = dt.date.today().isoformat()
    lines = [
        f'SWU Buy List — generated {today}',
        f'Playset target: {PLAYSET} copies per card. '
        f'Prices: TCGplayer via tcgcsv.com (Normal printing).',
    ]
    if not include_leaders_bases:
        lines.append('Leaders and bases excluded (run with --all to include them).')
    lines.append('')
    grand_market = grand_low = 0.0
    grand_cards = grand_copies = 0

    for set_name in set_names:
        set_name = set_name.lower()
        try:
            sheet = spreadsheet.worksheet(set_name.upper())
        except Exception:
            print(f'Skipping {set_name.upper()}: no tab in the spreadsheet')
            continue

        skip = set() if include_leaders_bases else leader_base_numbers(set_name)
        missing, blanks, skipped = missing_cards_for_sheet(sheet, skip)
        notes = []
        if blanks:
            notes.append(f'{blanks} blank-count cards ignored')
        if skipped:
            notes.append(f'skipped {skipped} leaders/bases')
        note = f" ({'; '.join(notes)})" if notes else ''
        print(f'{set_name.upper()}: {len(missing)} cards short of a playset{note}')
        if not missing:
            continue

        price_map = tcgcsv.get_price_map(set_name)
        section, market_total, low_total = build_set_section(
            set_name, missing, price_map, blanks)
        lines.extend(section)
        grand_market += market_total
        grand_low += low_total
        grand_cards += len(missing)
        grand_copies += sum(c['need'] for c in missing)

    lines.append(f'=== TOTAL: {grand_cards} cards / {grand_copies} copies — '
                 f'market {format_money(grand_market)}, low {format_money(grand_low)} ===')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'\nBuy list written to {output_path}')
    print(lines[-1])


if __name__ == '__main__':
    args = sys.argv[1:]
    output = DEFAULT_OUTPUT
    include_all = '--all' in args
    if include_all:
        args.remove('--all')
    if '-o' in args:
        idx = args.index('-o')
        try:
            output = args[idx + 1]
        except IndexError:
            print('Error: -o requires a file path')
            sys.exit(1)
        del args[idx:idx + 2]

    generate_buy_list(args, output, include_leaders_bases=include_all)
