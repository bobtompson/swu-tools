#!/usr/bin/env python3
"""
Find which decks use a card, across the grouping databases built by
update_used_card_list.py.

    uv run python find_card.py ash 199
    uv run python find_card.py "ASH 199"          # single argument works too
    uv run python find_card.py ash 199 --db twin_suns_lists
    uv run python find_card.py --list             # show available databases

Searches every grouping database in card_data/ (one per deck-list file)
and reports each deck that plays the card, with main/sideboard quantities.
"""

import argparse
import os
import re
import sqlite3
import sys

import lib.swudb as swudb

CARD_DATA_DIR = os.path.join(os.path.dirname(__file__), 'card_data')

# Must match update_used_card_list.SCHEMA_VERSION — used to recognize
# grouping databases among other .db files in card_data/.
SCHEMA_VERSION = 1

INVENTORY_DB = os.path.join(CARD_DATA_DIR, 'inventory.db')


def grouping_databases():
    """(stem, path) for every grouping database in card_data/."""
    found = []
    if not os.path.isdir(CARD_DATA_DIR):
        return found
    for filename in sorted(os.listdir(CARD_DATA_DIR)):
        if not filename.endswith('.db'):
            continue
        path = os.path.join(CARD_DATA_DIR, filename)
        try:
            conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            conn.close()
        except sqlite3.Error:
            continue
        if version == SCHEMA_VERSION:
            found.append((os.path.splitext(filename)[0], path))
    return found


def search_db(path, set_abbr, number):
    """Deck rows using the card in one grouping database."""
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT d.title, d.url, d.format, c.name,
               dc.main_qty, dc.side_qty
        FROM cards c
        JOIN deck_cards dc ON dc.card_id = c.id
        JOIN decks d ON d.id = dc.deck_id
        WHERE c.set_abbr = ? AND c.number = ?
        ORDER BY d.id
    ''', (set_abbr, number)).fetchall()
    conn.close()
    return rows


def lookup_card_name(set_abbr, number):
    """Card name from the local swu-db cache, or '' if unavailable."""
    if set_abbr.lower() not in swudb.VALID_SETS:
        return ''
    df = swudb.get_swu_list(set_abbr.lower())
    if df is None:
        return ''
    name = swudb.get_card_name(df, number)
    if name:
        subtitle_row = df[df['Number'] == number]
        subtitle = str(subtitle_row.iloc[0].get('Subtitle') or '') if not subtitle_row.empty else ''
        return f'{name} - {subtitle}' if subtitle and subtitle != 'nan' else name
    return ''


# Column E variant-ownership codes (hand-entered in the sheet). Other
# codes exist for judge/prize versions; unknown tokens are shown as-is.
VARIANT_CODES = {
    'P1': 'Prestige',
    'P2': 'Prestige Foil',
    'P3': 'Serialized',
    'S': 'Showcase',
}

# Tolerates the hand-entered variations seen in the sheet: '2xP2', '1x S',
# '1xP1 1xP2', 'P3(127/250)' — comma or space separated, optional space
# around the 'x'.
_VARIANT_TOKEN = re.compile(
    r'(?:(?P<qty>\d+)\s*[xX]\s*)?(?P<code>[A-Za-z]+\d*)'
    r'(?:\s*(?P<detail>\([^)]*\)))?')


def decode_variants(raw):
    """Decode a column E variant string like '2xP2,1xP3(127/250)'.

    -> '2× Prestige Foil, 1× Serialized (127/250)'. Unrecognized tokens
    pass through untouched so judge/prize codes stay visible.
    """
    parts = []
    for m in _VARIANT_TOKEN.finditer(raw):
        label = VARIANT_CODES.get(m.group('code').upper())
        if label is None:
            parts.append(m.group(0).strip())
            continue
        qty = m.group('qty')
        detail = f" {m.group('detail')}" if m.group('detail') else ''
        parts.append(f"{qty or 1}× {label}{detail}")
    return ', '.join(parts)


def inventory_status(set_abbr, number):
    """Owned-count summary lines from the inventory snapshot, or None.

    The sheet's Count column tracks binder copies up to a playset of 4;
    anything beyond that lives untracked in bulk/trade boxes. Column E
    variant codes (prestige/showcase/serialized) are decoded when present.
    """
    if not os.path.exists(INVENTORY_DB):
        return None
    conn = sqlite3.connect(f'file:{INVENTORY_DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT count, variants FROM inventory '
        'WHERE set_abbr = ? AND number = ?',
        (set_abbr, number)).fetchone()
    meta = conn.execute(
        'SELECT synced_at FROM sync_meta WHERE set_abbr = ?',
        (set_abbr,)).fetchone()
    conn.close()

    synced = f" (synced {meta['synced_at']})" if meta else ''
    if row is None:
        return f'Inventory: no {set_abbr} data in snapshot — run sync_inventory.py'
    count = row['count']
    if count is None:
        status = f'Inventory: not tracked in sheet{synced}'
    elif count < 4:
        where = 'in binder' if count else 'owned'
        status = f'Inventory: {count} {where}{synced}'
    else:
        extra = (f', {count - 4} in bulk/trade' if count > 4
                 else '; extras (if any) in bulk/trade boxes')
        status = f'Inventory: 4 in binder{extra}{synced}'
    if row['variants']:
        status += f'\nVariants owned: {decode_variants(row["variants"])}'
    return status


def cmd_list():
    databases = grouping_databases()
    if not databases:
        print("No grouping databases found in card_data/.")
        print("Build one with: uv run python update_used_card_list.py <list-file>")
        return
    print(f"Grouping databases ({len(databases)}):\n")
    for stem, path in databases:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        deck_count = conn.execute('SELECT COUNT(*) FROM decks').fetchone()[0]
        card_count = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
        conn.close()
        print(f"  {stem}: {deck_count} decks, {card_count} unique cards")


def main():
    parser = argparse.ArgumentParser(
        description='Find which tracked decks use a card (e.g. ASH 199).')
    parser.add_argument('card', nargs='*',
                        help='Set abbreviation and card number: ASH 199')
    parser.add_argument('--db', metavar='STEM',
                        help='Only search this grouping database (list-file stem)')
    parser.add_argument('--list', action='store_true',
                        help='List available grouping databases and exit')
    args = parser.parse_args()

    if args.list:
        cmd_list()
        return

    parts = ' '.join(args.card).replace(',', ' ').split()
    if len(parts) != 2 or not parts[1].isdigit():
        parser.error("expected a set abbreviation and card number, e.g.: ash 199")
    set_abbr = parts[0].upper()
    number = parts[1].zfill(3)

    databases = grouping_databases()
    if args.db:
        databases = [(stem, path) for stem, path in databases if stem == args.db]
        if not databases:
            print(f"Error: No grouping database named '{args.db}' in card_data/.")
            sys.exit(1)
    if not databases:
        print("No grouping databases found in card_data/.")
        print("Build one with: uv run python update_used_card_list.py <list-file>")
        sys.exit(1)

    cache_name = lookup_card_name(set_abbr, number)
    header = f'{set_abbr} {number}'
    if cache_name:
        header += f': {cache_name}'
    print(header)
    status = inventory_status(set_abbr, number)
    if status:
        print(status)

    total = 0
    hits = 0
    for stem, path in databases:
        rows = search_db(path, set_abbr, number)
        if not rows:
            continue
        hits += 1
        print(f"\n{stem}:")
        for row in rows:
            qty_bits = []
            if row['main_qty']:
                qty_bits.append(f"{row['main_qty']} main")
            if row['side_qty']:
                qty_bits.append(f"{row['side_qty']} side")
            print(f"  {row['title']} ({row['format']}) — {', '.join(qty_bits)}")
            total += row['main_qty'] + row['side_qty']

    if hits:
        print(f"\nTotal copies in use: {total}")
    else:
        searched = args.db or f'{len(databases)} database(s)'
        print(f"Not used in any tracked deck ({searched} searched).")


if __name__ == '__main__':
    main()
