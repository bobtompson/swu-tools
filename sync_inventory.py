#!/usr/bin/env python3
"""
Snapshot the Google Sheets inventory into a local database.

Reads each set tab of the "SWU Sets Playset" spreadsheet (card names in
column B, owned counts in column C) and writes card_data/inventory.db so
other scripts (find_card.py) can show owned counts without hitting the
Google Sheets API.

    uv run python sync_inventory.py            # every set tab
    uv run python sync_inventory.py law ash    # specific sets

Count semantics (how the sheet is maintained):
  - The Count column tracks copies stored in the collection binders,
    up to a playset of 4 — a count under 4 means that's everything,
    and it's in the binder.
  - Copies beyond 4 live in bulk/trade boxes and are not systematically
    tracked; a count of 4+ means "binder playset, maybe extras elsewhere".
  - A blank cell means the card isn't tracked (stored as NULL); an
    explicit 0 marks a wanted card owned zero times.
  - Column E tracks owned variant printings as hand-entered codes, e.g.
    "2xP2,1xP3(127/250)": P1 = non-foil prestige, P2 = foil prestige,
    P3(serial) = serialized with its serial number, S = showcase (on
    leaders). Other codes exist for judge/prize versions and are stored
    as-is. Stored raw in the `variants` column.

The per-set sync time and the tab's "Prices Updated" stamp (K1, written
by update_prices.py) are recorded in the sync_meta table.
"""

import os
import sqlite3
import sys
from datetime import datetime

import lib.swudb as swudb
from main import get_spreadsheet

DB_PATH = os.path.join(os.path.dirname(__file__), 'card_data', 'inventory.db')

# Grouping databases from update_used_card_list.py use user_version = 1;
# this marker keeps find_card.py's grouping scan from picking up
# inventory.db as a deck database.
SCHEMA_VERSION = 2


def open_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            set_abbr TEXT NOT NULL,
            number TEXT NOT NULL,
            name TEXT NOT NULL,
            count INTEGER,
            variants TEXT,
            PRIMARY KEY (set_abbr, number)
        )
    ''')
    columns = {row[1] for row in cursor.execute('PRAGMA table_info(inventory)')}
    if 'variants' not in columns:  # snapshot db from before column E tracking
        cursor.execute('ALTER TABLE inventory ADD COLUMN variants TEXT')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_meta (
            set_abbr TEXT PRIMARY KEY,
            synced_at TEXT NOT NULL,
            card_count INTEGER NOT NULL,
            prices_updated TEXT
        )
    ''')
    conn.commit()
    return conn


def parse_count(value):
    """Sheet cell -> owned count. Blank means not tracked (None)."""
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def sync_set(conn, worksheet):
    """Snapshot one set tab into the database. Returns rows stored."""
    set_abbr = worksheet.title.upper()
    ranges = worksheet.batch_get(['H1', 'B3:E', 'K1'])
    try:
        card_count = int(ranges[0][0][0])
    except (IndexError, ValueError):
        print(f"  {set_abbr}: no card count in H1, skipped")
        return 0
    rows = ranges[1]
    prices_updated = None
    try:
        prices_updated = ranges[2][0][0]
    except IndexError:
        pass

    cursor = conn.cursor()
    cursor.execute('DELETE FROM inventory WHERE set_abbr = ?', (set_abbr,))
    stored = 0
    untracked = 0
    for num in range(1, card_count + 1):
        row = rows[num - 1] if num - 1 < len(rows) else []
        name = str(row[0]).strip() if len(row) >= 1 else ''
        count = parse_count(row[1]) if len(row) >= 2 else None
        # B=0, C=1, D=2 (rarity, unused), E=3 (variant codes)
        variants = str(row[3]).strip() if len(row) >= 4 else ''
        if count is None:
            untracked += 1
        cursor.execute('''
            INSERT INTO inventory (set_abbr, number, name, count, variants)
            VALUES (?, ?, ?, ?, ?)
        ''', (set_abbr, f'{num:03d}', name, count, variants or None))
        stored += 1

    cursor.execute('''
        INSERT INTO sync_meta (set_abbr, synced_at, card_count, prices_updated)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(set_abbr) DO UPDATE SET
            synced_at = excluded.synced_at,
            card_count = excluded.card_count,
            prices_updated = excluded.prices_updated
    ''', (set_abbr, datetime.now().strftime('%Y-%m-%d %H:%M'),
          card_count, prices_updated))
    conn.commit()

    note = f", {untracked} untracked" if untracked else ""
    print(f"  {set_abbr}: {stored} cards{note}")
    return stored


def main():
    requested = [arg.lower() for arg in sys.argv[1:]]
    for set_name in requested:
        if set_name not in swudb.VALID_SETS:
            print(f"Invalid set: {set_name}. "
                  f"Valid sets: {', '.join(swudb.VALID_SETS)}")
            sys.exit(1)

    spreadsheet = get_spreadsheet()
    worksheets = {ws.title.upper(): ws for ws in spreadsheet.worksheets()}
    if requested:
        targets = []
        for set_name in requested:
            ws = worksheets.get(set_name.upper())
            if ws is None:
                print(f"No tab named {set_name.upper()} in the spreadsheet.")
                sys.exit(1)
            targets.append(ws)
    else:
        targets = [worksheets[s] for s in swudb.VALID_SETS_UPPER
                   if s in worksheets]

    conn = open_db()
    print(f"Syncing {len(targets)} set tab(s) to {DB_PATH}")
    try:
        for ws in targets:
            sync_set(conn, ws)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
