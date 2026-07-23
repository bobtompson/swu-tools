#!/usr/bin/env python3
"""
Build a card-usage database and summary report from a list of SWUDB decks.

Input is a text file with one SWUDB deck URL per line (markdown bullet
lists like swudb_lists/twin_suns_lists.md work too — the first swudb.com
deck URL on each line is used). Each run rebuilds the grouping from
scratch, so re-run after editing the list to stay in sync.

    uv run python update_used_card_list.py swudb_lists/twin_suns_lists.md

Outputs, named after the input file:
  - card_data/<stem>.db          SQLite database of decks and their cards
  - <input dir>/<stem>-report.md per-deck summary (name, format, leaders,
                                 base, aspects, card counts) — no card lists

Use find_card.py to look up which decks in these databases use a card.
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

import requests

import validate_deck_format as vdf
from lib.deck_source import card_identity, load_deck

CARD_DATA_DIR = os.path.join(os.path.dirname(__file__), 'card_data')

DECK_URL_RE = re.compile(r'https?://(?:www\.)?swudb\.com/deck/[A-Za-z0-9]+')

# Marks databases created by this script so find_card.py can tell them
# apart from other .db files in card_data/.
SCHEMA_VERSION = 1


def parse_url_list(path):
    """Extract SWUDB deck URLs from a list file, one per line.

    Blank lines and lines starting with '#' are skipped. Duplicate URLs
    are dropped (first occurrence wins). Returns (urls, skipped_lines).
    """
    urls = []
    seen = set()
    skipped = []
    with open(path, 'r', encoding='utf-8') as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            match = DECK_URL_RE.search(line)
            if not match:
                skipped.append((line_no, line))
                continue
            url = match.group(0)
            if url in seen:
                print(f"  Line {line_no}: duplicate URL skipped: {url}")
                continue
            seen.add(url)
            urls.append(url)
    return urls, skipped


def classify_format(deck, premier_names):
    """Human-readable format for a URL-sourced deck.

    SWUDB has no Eternal format code — Eternal decks are saved as Premier
    (code 1), so code-1 decks are classified by legality: Premier-legal
    decks are 'Premier', otherwise Eternal-legal decks are 'Eternal'.
    """
    code = deck['deck_format_code']
    if code == 2:
        return 'Twin Suns'
    if code == 3:
        return 'Trilogy'
    if code == 1:
        if not vdf.validate_premier(deck, premier_names):
            return 'Premier'
        if not vdf.validate_eternal(deck):
            return 'Eternal'
        return 'Premier (illegal)'
    return f'Unknown (code {code})'


def summarize_deck(deck, url, premier_names):
    """Reduce a normalized deck to the summary row stored and reported."""
    leaders = [vdf.format_card_name(c) for c in deck['leaders']]
    base = vdf.format_card_name(deck['base']) if deck['base'] else ''
    return {
        'deck_id': vdf.extract_deck_id(url),
        'title': deck['title'],
        'url': url,
        'format': classify_format(deck, premier_names),
        'leaders': ' / '.join(leaders),
        'base': base,
        'aspects': ', '.join(vdf.aspect_names(deck['aspects'])),
        'main_count': sum(e['quantity'] for e in deck['mainboard']),
        'side_count': sum(e['quantity'] for e in deck['sideboard']),
    }


def create_db(db_path):
    """Create a fresh grouping database, replacing any existing one."""
    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('PRAGMA foreign_keys = ON')
    cursor.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')

    cursor.execute('''
        CREATE TABLE decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            format TEXT NOT NULL,
            leaders TEXT NOT NULL,
            base TEXT NOT NULL,
            aspects TEXT NOT NULL,
            main_count INTEGER NOT NULL,
            side_count INTEGER NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_abbr TEXT NOT NULL,
            number TEXT NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(set_abbr, number)
        )
    ''')
    cursor.execute('''
        CREATE TABLE deck_cards (
            deck_id INTEGER NOT NULL,
            card_id INTEGER NOT NULL,
            main_qty INTEGER NOT NULL DEFAULT 0,
            side_qty INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (deck_id, card_id),
            FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE,
            FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    return conn


def store_deck(conn, deck, summary):
    """Insert one deck and its cards (leaders, base, main, side) into the db."""
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO decks (deck_id, title, url, format, leaders, base,
                           aspects, main_count, side_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (summary['deck_id'], summary['title'], summary['url'],
          summary['format'], summary['leaders'], summary['base'],
          summary['aspects'], summary['main_count'], summary['side_count']))
    deck_row_id = cursor.lastrowid

    # (set, number) -> [main_qty, side_qty, name]
    counts = {}

    def add(card_data, main_qty, side_qty):
        if not card_data:
            return
        set_abbr, number = card_identity(card_data)
        name = vdf.format_card_name(card_data)
        if not (set_abbr and number and name):
            return
        entry = counts.setdefault((set_abbr, number), [0, 0, name])
        entry[0] += main_qty
        entry[1] += side_qty

    for leader in deck['leaders']:
        add(leader, 1, 0)
    add(deck['base'], 1, 0)
    for entry in deck['mainboard']:
        add(entry['card'], entry['quantity'], 0)
    for entry in deck['sideboard']:
        add(entry['card'], 0, entry['quantity'])

    for (set_abbr, number), (main_qty, side_qty, name) in counts.items():
        cursor.execute('''
            INSERT INTO cards (set_abbr, number, name) VALUES (?, ?, ?)
            ON CONFLICT(set_abbr, number) DO NOTHING
        ''', (set_abbr, number, name))
        cursor.execute(
            'SELECT id FROM cards WHERE set_abbr = ? AND number = ?',
            (set_abbr, number))
        card_row_id = cursor.fetchone()[0]
        cursor.execute('''
            INSERT INTO deck_cards (deck_id, card_id, main_qty, side_qty)
            VALUES (?, ?, ?, ?)
        ''', (deck_row_id, card_row_id, main_qty, side_qty))

    conn.commit()


def write_report(report_path, list_path, summaries, failures, skipped):
    """Write the per-deck markdown summary report."""
    stem = os.path.splitext(os.path.basename(list_path))[0]
    lines = [
        f'# Deck Report: {stem}',
        '',
        f'Source: `{list_path}` — generated {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        '',
        f'## Decks ({len(summaries)})',
        '',
        '| # | Deck | Format | Leaders | Base | Aspects | Cards |',
        '|---|------|--------|---------|------|---------|-------|',
    ]
    for idx, s in enumerate(summaries, 1):
        cards = str(s['main_count'])
        if s['side_count']:
            cards += f" (+{s['side_count']} side)"
        lines.append(
            f"| {idx} | [{s['title']}]({s['url']}) | {s['format']} "
            f"| {s['leaders']} | {s['base']} | {s['aspects']} | {cards} |"
        )

    if failures:
        lines += ['', f'## Failed to fetch ({len(failures)})', '']
        for url, error in failures:
            lines.append(f'- {url} — {error}')

    if skipped:
        lines += ['', f'## Skipped lines (no deck URL) ({len(skipped)})', '']
        for line_no, text in skipped:
            lines.append(f'- Line {line_no}: `{text}`')

    lines.append('')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def build_grouping(list_path):
    """Fetch every deck in the list file; build its database and report."""
    if not os.path.exists(list_path):
        print(f"Error: List file not found: {list_path}")
        return False

    urls, skipped = parse_url_list(list_path)
    for line_no, text in skipped:
        print(f"  Line {line_no}: no deck URL found, skipped: {text}")
    if not urls:
        print(f"Error: No SWUDB deck URLs found in {list_path}")
        return False

    stem = os.path.splitext(os.path.basename(list_path))[0]
    db_path = os.path.join(CARD_DATA_DIR, f'{stem}.db')
    report_path = os.path.join(os.path.dirname(os.path.abspath(list_path)),
                               f'{stem}-report.md')

    # Premier reprint names are needed to classify code-1 decks; build once.
    premier_names = vdf.get_premier_reprint_names()

    conn = create_db(db_path)
    summaries = []
    failures = []
    try:
        for idx, url in enumerate(urls, 1):
            print(f"[{idx}/{len(urls)}] Fetching {url}")
            try:
                deck = load_deck(url)
            except (requests.RequestException, ValueError) as exc:
                print(f"  Error: {exc}")
                failures.append((url, str(exc)))
                continue
            summary = summarize_deck(deck, url, premier_names)
            store_deck(conn, deck, summary)
            summaries.append(summary)
            print(f"  {summary['title']} ({summary['format']}) — "
                  f"{summary['leaders']}")
    finally:
        conn.close()

    write_report(report_path, list_path, summaries, failures, skipped)

    print(f"\nDatabase: {db_path}")
    print(f"Report:   {report_path}")
    print(f"  Decks: {len(summaries)}" +
          (f", failed: {len(failures)}" if failures else ""))
    return not failures


def main():
    parser = argparse.ArgumentParser(
        description='Build a card-usage database and report from a file of '
                    'SWUDB deck URLs (one per line).')
    parser.add_argument('list_file',
                        help='Text/markdown file with one SWUDB deck URL per line')
    args = parser.parse_args()

    success = build_grouping(args.list_file)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
