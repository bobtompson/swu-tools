#!/usr/bin/env python3
"""
Track cards in use across multiple SWUDB decks.

Maintains a SQLite database of all cards used in tracked decks,
with CLI commands to add/remove decks and generate a markdown summary.
"""

import sys
import os
import sqlite3
import argparse
from datetime import datetime
from collections import defaultdict
import requests
from lib.swudb import MAIN_SETS_UPPER, SPECIAL_SETS_UPPER
from lib.deck_source import card_identity, load_deck
import validate_deck_format as vdf

ORDERED_SETS = MAIN_SETS_UPPER + SPECIAL_SETS_UPPER

# Database and output paths
DB_PATH = os.path.join(os.path.dirname(__file__), 'card_data', 'cards_in_use.db')
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'swudb_lists', 'cards_in_use.md')

# Deck format mapping
DECK_FORMATS = {
    1: 'Premier',
    2: 'Twin Suns'
}


def init_db():
    """Initialize the SQLite database with required tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # SQLite ships with foreign-key enforcement off; without this the
    # ON DELETE CASCADE on deck_cards never fires and orphan rows accumulate.
    cursor.execute('PRAGMA foreign_keys = ON')

    # Create decks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            format TEXT NOT NULL,
            added_at TEXT NOT NULL
        )
    ''')
    
    # Create cards table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            primary_set TEXT NOT NULL,
            primary_number TEXT NOT NULL,
            alternate_sets TEXT DEFAULT '[]',
            use_count INTEGER DEFAULT 0,
            UNIQUE(primary_set, primary_number)
        )
    ''')
    
    # Create deck_cards junction table with quantity
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deck_cards (
            deck_id INTEGER NOT NULL,
            card_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            PRIMARY KEY (deck_id, card_id),
            FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE,
            FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    return conn


def _summarize_deck(deck, url):
    """Flatten a normalized deck (lib.deck_source) into the legacy SQLite shape.

    Returns {deck_id, title, url, format, cards} where cards is a list of
    {name, set, number, quantity} merged across leaders / base / mainboard / sideboard.
    """
    counts = {}

    def add(card_data, qty):
        if not card_data or qty <= 0:
            return
        name = vdf.format_card_name(card_data)
        set_abbr, number = card_identity(card_data)
        if not (name and set_abbr and number):
            return
        key = (set_abbr, number)
        if key in counts:
            counts[key]['quantity'] += qty
        else:
            counts[key] = {
                'name': name,
                'set': set_abbr,
                'number': number,
                'quantity': qty,
            }

    for leader in deck['leaders']:
        add(leader, 1)
    add(deck['base'], 1)
    for entry in deck['mainboard']:
        add(entry['card'], entry['quantity'])
    for entry in deck['sideboard']:
        add(entry['card'], entry['quantity'])

    return {
        'deck_id': vdf.extract_deck_id(url),
        'title': deck['title'],
        'url': url,
        'format': DECK_FORMATS.get(deck['deck_format_code'], 'Unknown'),
        'cards': list(counts.values()),
    }


def cmd_add(conn, url):
    """Add a deck to tracking."""
    if not vdf.is_swudb_url(url):
        print(f"Error: Invalid SWUDB URL: {url}")
        return False

    print(f"Fetching deck from: https://www.swudb.com/api/deck/{vdf.extract_deck_id(url)}")
    try:
        deck = load_deck(url)
    except (requests.RequestException, ValueError) as exc:
        print(f"Error: {exc}")
        return False

    deck_data = _summarize_deck(deck, url)
    if not deck_data['deck_id']:
        print(f"Error: Could not extract deck ID from URL: {url}")
        return False
    
    cursor = conn.cursor()
    
    # Check if deck already exists
    cursor.execute('SELECT id FROM decks WHERE deck_id = ?', (deck_data['deck_id'],))
    if cursor.fetchone():
        print(f"Error: Deck '{deck_data['title']}' is already being tracked.")
        print("Use 'remove' first if you want to re-add it.")
        return False
    
    # Insert deck
    cursor.execute('''
        INSERT INTO decks (deck_id, title, url, format, added_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        deck_data['deck_id'],
        deck_data['title'],
        deck_data['url'],
        deck_data['format'],
        datetime.now().isoformat()
    ))
    deck_row_id = cursor.lastrowid
    
    # Process each card with quantity
    cards_added = 0
    total_cards = 0
    for card in deck_data['cards']:
        qty = card.get('quantity', 1)
        
        # Upsert card - increment use_count by quantity
        cursor.execute('''
            INSERT INTO cards (name, primary_set, primary_number, use_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(primary_set, primary_number) DO UPDATE SET
                use_count = use_count + ?
        ''', (card['name'], card['set'], card['number'], qty, qty))
        
        # Get card id
        cursor.execute(
            'SELECT id FROM cards WHERE primary_set = ? AND primary_number = ?',
            (card['set'], card['number'])
        )
        card_row_id = cursor.fetchone()[0]
        
        # Link deck to card with quantity
        cursor.execute('''
            INSERT INTO deck_cards (deck_id, card_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(deck_id, card_id) DO UPDATE SET quantity = ?
        ''', (deck_row_id, card_row_id, qty, qty))
        
        cards_added += 1
        total_cards += qty
    
    conn.commit()
    
    print(f"Added deck: {deck_data['title']} ({deck_data['format']})")
    print(f"  Unique cards: {cards_added}, Total cards: {total_cards}")
    
    # Auto-export
    cmd_export(conn)
    return True


def cmd_remove(conn, url):
    """Remove a deck from tracking."""
    deck_id = vdf.extract_deck_id(url)
    if not deck_id:
        print(f"Error: Could not extract deck ID from URL: {url}")
        return False
    
    cursor = conn.cursor()
    
    # Find the deck
    cursor.execute('SELECT id, title FROM decks WHERE deck_id = ?', (deck_id,))
    deck_row = cursor.fetchone()
    if not deck_row:
        print(f"Error: Deck not found in tracking: {deck_id}")
        return False
    
    deck_row_id, deck_title = deck_row['id'], deck_row['title']
    
    # Get all cards linked to this deck with their quantities
    cursor.execute('SELECT card_id, quantity FROM deck_cards WHERE deck_id = ?', (deck_row_id,))
    card_entries = [(row['card_id'], row['quantity']) for row in cursor.fetchall()]
    
    # Decrement use_count by quantity for each card
    for card_id, quantity in card_entries:
        cursor.execute('UPDATE cards SET use_count = use_count - ? WHERE id = ?', (quantity, card_id))
    
    # Delete deck (cascade will remove deck_cards entries)
    cursor.execute('DELETE FROM decks WHERE id = ?', (deck_row_id,))
    
    # Remove cards with use_count = 0
    cursor.execute('DELETE FROM cards WHERE use_count <= 0')
    removed_cards = cursor.rowcount
    
    conn.commit()
    
    print(f"Removed deck: {deck_title}")
    print(f"  Cards no longer in use: {removed_cards}")
    
    # Auto-export
    cmd_export(conn)
    return True


def cmd_remove_all(conn):
    """Remove all decks and cards, archiving the current markdown file."""
    cursor = conn.cursor()
    
    # Check if there's anything to remove
    cursor.execute('SELECT COUNT(*) as count FROM decks')
    deck_count = cursor.fetchone()['count']
    
    if deck_count == 0:
        print("No decks are currently being tracked.")
        return False
    
    # Archive the current markdown file if it exists
    if os.path.exists(OUTPUT_PATH):
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        base, ext = os.path.splitext(OUTPUT_PATH)
        archive_path = f"{base}_{timestamp}{ext}"
        os.rename(OUTPUT_PATH, archive_path)
        print(f"Archived: {archive_path}")
    
    # Get counts before clearing
    cursor.execute('SELECT COUNT(*) as count FROM cards')
    card_count = cursor.fetchone()['count']
    
    # Clear all tables
    cursor.execute('DELETE FROM deck_cards')
    cursor.execute('DELETE FROM cards')
    cursor.execute('DELETE FROM decks')
    
    conn.commit()
    
    print("Removed all data:")
    print(f"  Decks removed: {deck_count}")
    print(f"  Cards removed: {card_count}")
    
    return True


def cmd_list(conn):
    """List all tracked decks."""
    cursor = conn.cursor()
    cursor.execute('SELECT title, format, url, added_at FROM decks ORDER BY added_at')
    decks = cursor.fetchall()
    
    if not decks:
        print("No decks are currently being tracked.")
        return
    
    print(f"\nTracked Decks ({len(decks)}):\n")
    for deck in decks:
        print(f"  • {deck['title']} ({deck['format']})")
        print(f"    {deck['url']}")
        print(f"    Added: {deck['added_at'][:10]}")
        print()


def cmd_export(conn):
    """Export cards in use to markdown file."""
    cursor = conn.cursor()
    
    # Get all decks with their row IDs for reference
    cursor.execute('SELECT id, title, format, url FROM decks ORDER BY added_at')
    decks = cursor.fetchall()
    
    # Build deck lookup by id -> index (1-based)
    deck_index = {d['id']: idx + 1 for idx, d in enumerate(decks)}
    
    # Get all cards grouped by set
    cursor.execute('''
        SELECT id, name, primary_set, primary_number, alternate_sets, use_count
        FROM cards
        ORDER BY primary_set, primary_number
    ''')
    cards = cursor.fetchall()
    
    # Get deck associations for each card (as index:quantity pairs)
    card_decks = {}
    cursor.execute('''
        SELECT card_id, deck_id, quantity FROM deck_cards
    ''')
    for row in cursor.fetchall():
        card_id = row['card_id']
        if card_id not in card_decks:
            card_decks[card_id] = []
        idx = deck_index.get(row['deck_id'], 0)
        qty = row['quantity']
        card_decks[card_id].append((idx, qty))
    
    # Group cards by set
    grouped = defaultdict(list)
    for card in cards:
        grouped[card['primary_set']].append(card)
    
    # Build output
    lines = ['# Cards In Use\n']
    
    # Deck list section with indices
    if decks:
        lines.append(f'## Tracked Decks ({len(decks)})\n')
        for idx, deck in enumerate(decks, 1):
            lines.append(f"- [{idx}] [{deck['title']}]({deck['url']}) ({deck['format']})")
        lines.append('')
    
    # Cards section
    total_cards = len(cards)
    lines.append(f'## Cards ({total_cards} unique)\n')
    lines.append('Format: `- NUMBER: Card Name (xTOTAL) [DECK:QTY, ...]`\n')
    
    # Sort sets: main sets first in order, then others alphabetically
    all_sets = list(grouped.keys())
    known_sets = [s for s in ORDERED_SETS if s in all_sets]
    unknown_sets = sorted([s for s in all_sets if s not in ORDERED_SETS])
    ordered_sets = known_sets + unknown_sets
    
    for set_abbr in ordered_sets:
        set_cards = grouped[set_abbr]
        lines.append(f"\n### {set_abbr} ({len(set_cards)} cards)\n")
        
        for card in set_cards:
            line = f"- {card['primary_number']}: {card['name']}"
            if card['use_count'] > 1:
                line += f" (x{card['use_count']})"
            # Add deck indices with quantities [1:3, 2:1]
            deck_entries = card_decks.get(card['id'], [])
            if deck_entries:
                # Sort by deck index
                deck_entries.sort(key=lambda x: x[0])
                entries_str = ', '.join(f"{idx}:{qty}" for idx, qty in deck_entries)
                line += f" [{entries_str}]"
            lines.append(line)
    
    # Write output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"\nExported to: {OUTPUT_PATH}")
    print(f"  Decks: {len(decks)}")
    print(f"  Unique cards: {total_cards}")


def main():
    parser = argparse.ArgumentParser(
        description='Track cards in use across multiple SWUDB decks.'
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a deck to tracking')
    add_parser.add_argument('url', help='SWUDB deck URL')
    
    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove a deck from tracking')
    remove_parser.add_argument('url', help='SWUDB deck URL')
    
    # Remove all command
    subparsers.add_parser('remove-all', help='Remove all decks and archive markdown')
    
    # List command
    subparsers.add_parser('list', help='List all tracked decks')
    
    # Export command
    subparsers.add_parser('export', help='Regenerate markdown output')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Initialize database
    conn = init_db()
    
    try:
        if args.command == 'add':
            success = cmd_add(conn, args.url)
            sys.exit(0 if success else 1)
        elif args.command == 'remove':
            success = cmd_remove(conn, args.url)
            sys.exit(0 if success else 1)
        elif args.command == 'remove-all':
            success = cmd_remove_all(conn)
            sys.exit(0 if success else 1)
        elif args.command == 'list':
            cmd_list(conn)
        elif args.command == 'export':
            cmd_export(conn)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
