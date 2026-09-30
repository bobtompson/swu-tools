"""Check whether swu-db's card list for a set is complete and current.

swu-db lags during spoiler season and right up to release. Run this before
main.py: it compares the live card list against the set's announced card
count, then against the local card_data/ cache that main.py actually reads.

Usage:
    uv run python validate_set.py hmw              # live list vs catalog vs cache
    uv run python validate_set.py hmw ic27         # several sets
    uv run python validate_set.py hmw --refresh    # also save the live list to the cache
    uv run python validate_set.py hmw --sheet      # also preview main.py's spreadsheet changes

Exit code 0 means every set is complete online and the cache matches (ready
for main.py); 1 means something is missing or stale.
"""

import argparse
import json
import os
import sys

import requests

from lib.swudb import (
    RELEASE_DATE_OVERRIDES,
    VALID_SETS,
    fetch_remote_cards,
    get_cache_path,
    get_sets_catalog,
    save_to_cache,
)

# How many individual numbers / changes to print before summarizing
MAX_LISTED = 15


def base_cards(rows, card_count):
    """Map '001'.. -> card dict for the numbered cards 1..card_count.

    Variants (hyperspace, showcase, prestige) are numbered above the set's
    card count and tokens use 'T01'-style numbers, so both fall outside this
    range. Sub set caches store unpadded numbers, hence the zero-pad.
    """
    cards = {}
    for card in rows:
        number = str(card.get('Number', ''))
        if number.isdigit() and 1 <= int(number) <= card_count:
            cards.setdefault(number.zfill(3), card)
    return cards


def load_cached_rows(set_name):
    """Card rows from the local cache, or None if there's no cache file."""
    path = get_cache_path(set_name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def format_numbers(numbers):
    """Compact '001-004, 010' rendering of sorted 3-digit numbers."""
    ints = sorted(int(n) for n in numbers)
    ranges = []
    start = prev = ints[0]
    for n in ints[1:]:
        if n != prev + 1:
            ranges.append((start, prev))
            start = n
        prev = n
    ranges.append((start, prev))
    return ', '.join(f'{a:03d}' if a == b else f'{a:03d}-{b:03d}' for a, b in ranges)


def print_limited(lines, indent='    '):
    for line in lines[:MAX_LISTED]:
        print(f'{indent}{line}')
    if len(lines) > MAX_LISTED:
        print(f'{indent}... and {len(lines) - MAX_LISTED} more')


def rarity_letter(card):
    return str(card.get('Rarity') or '')[:1]


def check_online(online, card_count):
    """Report completeness of the live list. Returns True if complete."""
    ok = True
    missing = sorted(set(f'{n:03d}' for n in range(1, card_count + 1)) - set(online))
    if missing:
        ok = False
        print(f'  ✗ Missing {len(missing)} numbered card(s): {format_numbers(missing)}')

    blanks = [f"{num} {card.get('Name') or '(no name)'}: missing "
              + ', '.join(field for field in ('Name', 'Rarity') if not card.get(field))
              for num, card in sorted(online.items())
              if not card.get('Name') or not card.get('Rarity')]
    if blanks:
        ok = False
        print(f'  ✗ {len(blanks)} card(s) with blank fields:')
        print_limited(blanks)
    return ok


def check_cache(set_name, online, card_count, online_printings):
    """Compare the cached numbered cards against the live list.
    Returns True if main.py would see the same names and rarities."""
    cached_rows = load_cached_rows(set_name)
    if cached_rows is None:
        print(f'  ✗ No local cache — run with --refresh (or refresh_cache.py {set_name})')
        return False
    cached = base_cards(cached_rows, card_count)

    added = sorted(set(online) - set(cached))
    changes = []
    for num in sorted(set(online) & set(cached)):
        old, new = cached[num], online[num]
        if old.get('Name') != new.get('Name'):
            changes.append(f"{num} name: {old.get('Name')!r} -> {new.get('Name')!r}")
        if rarity_letter(old) != rarity_letter(new):
            changes.append(f"{num} rarity: {rarity_letter(old) or '-'} -> "
                           f"{rarity_letter(new) or '-'} ({new.get('Name')})")

    print(f'  Cache: {len(cached)}/{card_count} numbered cards, '
          f'{len(cached_rows)} printings total')
    if not added and not changes:
        print('  ✓ Cache matches the live list')
        if online_printings != len(cached_rows):
            # Doesn't affect main.py, but showcase/prestige pricing reads variants
            print(f'  ⚠ Variant printings differ ({len(cached_rows)} cached, '
                  f'{online_printings} online) — refresh_cache.py {set_name} '
                  f'before running showcase_prices.py / prestige_prices.py')
        return True
    if added:
        print(f'  ✗ {len(added)} card(s) online but not cached: {format_numbers(added)}')
    if changes:
        print(f'  ✗ {len(changes)} name/rarity change(s) since the cache was saved:')
        print_limited(changes)
    return False


def preview_sheet(set_name, online):
    """Show the column B/D cells main.py would change on the set's tab.
    Mirrors update_list_names: rows 001..H1, TS26 gets pre-con deck codes."""
    import main  # deferred: Google auth is only needed for --sheet

    try:
        sheet = main.get_doc_sheet(set_name.upper())
    except Exception as exc:  # gspread raises several unrelated types
        print(f'  ✗ Could not open the {set_name.upper()} tab: {exc}')
        return
    header, rows = sheet.batch_get(['H1', 'A3:D'])
    try:
        sheet_count = int(header[0][0])
    except (IndexError, ValueError):
        print(f'  ✗ {set_name.upper()} tab has no card count in H1')
        return

    is_ts26 = set_name == 'ts26'
    changes = []
    for i in range(sheet_count):
        num = f'{i + 1:03d}'
        row = (rows[i] if i < len(rows) else []) + [''] * 4
        card = online.get(num, {})
        name = str(card.get('Name', ''))
        rarity = main.get_ts26_deck_codes(num) if is_ts26 else rarity_letter(card)
        if row[1] != name:
            changes.append(f"B{i + 3} {num}: {row[1]!r} -> {name!r}")
        if row[3] != rarity:
            changes.append(f"D{i + 3} {num}: {row[3]!r} -> {rarity!r}")

    if not changes:
        print(f'  ✓ Sheet tab up to date ({sheet_count} rows)')
    else:
        print(f'  main.py would change {len(changes)} cell(s) on the '
              f'{set_name.upper()} tab ({sheet_count} rows):')
        print_limited(changes)
    if sheet_count != len(online):
        print(f'  ⚠ Tab H1 says {sheet_count} cards; the catalog/live list has '
              f'{len(online)} — main.py only fills rows 1..H1')


def validate_set(set_name, catalog, refresh, sheet):
    """Run all checks for one set. Returns True if ready for main.py."""
    set_id = set_name.upper()
    info = next((s for s in catalog if s.get('setId') == set_id), None)
    if info is None or not info.get('numberCards'):
        print(f'\n=== {set_id} ===')
        print('  ✗ Not in the swu-db /sets catalog yet (or no card count) — '
              'nothing to validate against')
        return False

    card_count = info['numberCards']
    release = RELEASE_DATE_OVERRIDES.get(set_id) or info.get('releaseDate') or '?'
    print(f"\n=== {set_id} — {info.get('fullName', '')} "
          f"(release {release}, {card_count} cards) ===")

    try:
        rows = fetch_remote_cards(set_name)
    except (requests.RequestException, ValueError) as exc:
        print(f'  ✗ Could not fetch the live card list: {exc}')
        return False

    online = base_cards(rows, card_count)
    extras = len(rows) - len(online)
    print(f'  Online: {len(online)}/{card_count} numbered cards, '
          f'{len(rows)} printings total ({extras} variants/tokens)')

    complete = check_online(online, card_count)
    if complete:
        print('  ✓ Live list is complete')

    cache_ok = check_cache(set_name, online, card_count, len(rows))
    if refresh and not cache_ok:
        save_to_cache(set_name, rows)
        cache_ok = True

    if sheet:
        preview_sheet(set_name, online)

    ready = complete and cache_ok
    if ready:
        print(f'  → Ready: main.py will use complete data for {set_id}')
    elif not complete:
        print('  → Not ready: swu-db is still missing cards — check back later')
    else:
        print(f'  → Refresh the cache first: validate_set.py {set_name} --refresh')
    return ready


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sets', nargs='+', help='set abbreviations (e.g. hmw)')
    parser.add_argument('--refresh', action='store_true',
                        help='save the live card list to card_data/ when the cache differs')
    parser.add_argument('--sheet', action='store_true',
                        help="preview the cells main.py would change on each set's tab")
    args = parser.parse_args()

    sets = [s.lower() for s in args.sets]
    unknown = [s for s in sets if s not in VALID_SETS]
    if unknown:
        print(f"Unknown set(s): {', '.join(unknown)}. Valid sets: {', '.join(VALID_SETS)}")
        return 2

    catalog = get_sets_catalog(force_refresh=True)
    if not catalog:
        print('Could not load the swu-db /sets catalog.')
        return 1

    results = [validate_set(s, catalog, args.refresh, args.sheet) for s in sets]
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
