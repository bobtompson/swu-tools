"""Show TCGplayer prices for a yearly promo set (P26 by default).

A promo set collects a season's organized-play printings: store showdown /
PQ / SQ / RQ / Galactic Championship prizes (participation, judge, top 8 ...
champion), prize wall and event pack cards, silver / black packs, tokens,
VIP bases, and a few leader showcases. swu-db labels each card's program in
VariantType (e.g. 'SQ Prize Wall', 'RQ Top 8') and carries a tcgplayerId,
which is how prices are matched — TCGplayer spreads one promo set over
several groups with its own numbering.

Each card also gets its original printing ('LAW 045'): the first-released
main/sub set with the same Name + Subtitle, blank for promo-only cards.

With --update-sheet the list is written to the promo set's own tab (P26),
which uses the Collector tab's layout (Card Num. / Card Name / Count /
Original Card Number / Source / Current Price). Rows are matched by card
number; Count and any other rows are left alone.

Usage:
    uv run python promo_prices.py                   # P26, console only
    uv run python promo_prices.py p25               # another promo set
    uv run python promo_prices.py --refresh         # re-fetch the promo set from swu-db first
    uv run python promo_prices.py --update-sheet    # also update the P26 tab
"""

import argparse
import json
import os
import sys

import lib.swudb as swudb
import lib.tcgcsv as tcgcsv
from showcase_prices import format_money, upsert_collector_rows

# Console sections: VariantType prefix -> program name, in display order.
# Labels matching no prefix get their own section.
PROGRAMS = [
    ('Store Showdown', 'Store Showdown'),
    ('PQ ', 'Planetary Qualifier'),
    ('SQ ', 'Sector Qualifier'),
    ('RQ ', 'Regional Qualifier'),
    ('GC ', 'Galactic Championship'),
    ('S1 ', 'Season 1 Leaderboard'),
    ('Showcase', 'Leader Showcases'),
]


def program_of(label):
    for prefix, name in PROGRAMS:
        if label.startswith(prefix):
            return name
    return label or 'Other'


def load_set_rows(set_name):
    """Card rows for a set from the local cache (fetching if not cached),
    without get_swu_list's per-set log line."""
    path = swudb.get_cache_path(set_name)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    df = swudb.get_swu_list(set_name)
    return [] if df is None else df.to_dict('records')


def card_key(card):
    """Case-insensitive Name + Subtitle — swu-db capitalizes subtitles
    inconsistently between sets ('Will be Short' vs 'Will Be Short')."""
    subtitle = card.get('Subtitle')
    subtitle = subtitle if isinstance(subtitle, str) else ''
    return str(card.get('Name', '')).strip().lower(), subtitle.strip().lower()


def build_original_index():
    """Map card_key -> 'SET NNN' for the earliest printing in VALID_SETS.

    Sets are visited in release order (catalog dates with overrides) so a
    reprinted card resolves to its first set; within a set the lowest
    number is the base printing (variants are numbered above the set).
    """
    catalog = {s.get('setId'): s for s in swudb.get_sets_catalog()}

    def release(set_name):
        raw = (swudb.RELEASE_DATE_OVERRIDES.get(set_name.upper())
               or catalog.get(set_name.upper(), {}).get('releaseDate'))
        parsed = swudb.parse_release_date(raw)
        return (parsed is None, parsed)

    index = {}
    for set_name in sorted(swudb.VALID_SETS, key=release):
        numbered = [c for c in load_set_rows(set_name)
                    if str(c.get('Number', '')).isdigit()]
        for card in sorted(numbered, key=lambda c: int(c['Number'])):
            index.setdefault(card_key(card), f"{set_name.upper()} {int(card['Number']):03d}")
    return index


def pick_price(printings, label):
    """Choose the TCGplayer printing for a promo card.

    Most promo products carry a single printing. When both exist, foil
    labels and showcases (foil-only cards some sellers list as Normal) use
    Foil, everything else Normal — falling back to whichever printing has
    a market price.
    """
    preferred, other = (('Foil', 'Normal') if 'Foil' in label or label == 'Showcase'
                        else ('Normal', 'Foil'))
    for name in (preferred, other):
        if (printings.get(name) or {}).get('market') is not None:
            return printings[name]
    return printings.get(preferred) or printings.get(other) or {}


def collect_promos(set_name, refresh=False):
    """Build the promo set's price list, sorted by card number.

    Entries: number, name, source (VariantType), original, product_id,
    market, low. Returns None if the set data can't be loaded.
    """
    df = swudb.get_swu_list(set_name, force_refresh=refresh, allow_unknown=True)
    if df is None:
        return None
    cards = [c for c in df.to_dict('records') if str(c.get('Number', '')).isdigit()]

    originals = build_original_index()
    # Main/sub set groups never hold promo products — no need to fetch them
    skip_groups = {tcgcsv.GROUPS[s][0] for s in swudb.VALID_SETS if s in tcgcsv.GROUPS}
    product_ids = {int(c['tcgplayerId']) for c in cards
                   if str(c.get('tcgplayerId') or '').isdigit()}
    products = tcgcsv.get_prices_by_product_id(product_ids, skip_groups)
    if products is None:
        products = {}

    entries = []
    for card in sorted(cards, key=lambda c: int(c['Number'])):
        subtitle = card.get('Subtitle')
        name = f"{card['Name']} - {subtitle}" if isinstance(subtitle, str) and subtitle else card['Name']
        label = str(card.get('VariantType') or '')
        tcg_id = str(card.get('tcgplayerId') or '')
        product = products.get(int(tcg_id)) if tcg_id.isdigit() else None
        price = pick_price(product['printings'], label) if product else {}
        entries.append({
            'number': f"{int(card['Number']):03d}",
            'name': name,
            'source': label,
            'original': originals.get(card_key(card), ''),
            'product_id': int(tcg_id) if tcg_id.isdigit() else None,
            'on_tcgplayer': product is not None,
            'market': price.get('market'),
            'low': price.get('low'),
        })
    return entries


def print_promos(set_name, entries):
    sections = {}
    for e in entries:
        sections.setdefault(program_of(e['source']), []).append(e)
    order = [name for _, name in PROGRAMS]
    ordered = sorted(sections, key=lambda s: order.index(s) if s in order else len(order))

    for section in ordered:
        rows = sections[section]
        print(f'\n=== {set_name.upper()} {section} ({len(rows)} cards) ===')
        for e in rows:
            original = e['original'] or '—'
            print(f"  {e['number']}  {e['name']:<42.42} {e['source']:<24.24} "
                  f"{original:<8}  market {format_money(e['market']):>9}  "
                  f"low {format_money(e['low']):>9}")
        total = sum(e['market'] or 0 for e in rows)
        print(f'  section total: market {format_money(total)}')

    grand = sum(e['market'] or 0 for e in entries)
    priced = sum(1 for e in entries if e['market'] is not None)
    print(f'\n{set_name.upper()}: {len(entries)} cards, {priced} with a market price, '
          f'total market {format_money(grand)}')
    no_id = [e['number'] for e in entries if e['product_id'] is None]
    unlisted = [e['number'] for e in entries if e['product_id'] and not e['on_tcgplayer']]
    no_original = sum(1 for e in entries if not e['original'])
    if no_id:
        print(f"  {len(no_id)} card(s) have no TCGplayer id in swu-db yet: {', '.join(no_id)}")
    if unlisted:
        print(f"  {len(unlisted)} TCGplayer id(s) not found in any group: {', '.join(unlisted)}")
    if no_original:
        print(f'  {no_original} card(s) with no original printing in the cached sets '
              f'(tokens / promo-only cards)')


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('set', nargs='?', default='p26', help='promo set id (default: p26)')
    parser.add_argument('--refresh', action='store_true',
                        help='re-fetch the promo set from swu-db (new promos appear all season)')
    parser.add_argument('--update-sheet', action='store_true',
                        help="write the list to the promo set's tab (e.g. P26)")
    args = parser.parse_args()

    set_name = args.set.lower()
    entries = collect_promos(set_name, refresh=args.refresh)
    if not entries:
        print(f'No card data for {set_name.upper()}.')
        return 1

    print_promos(set_name, entries)
    if args.update_sheet:
        upsert_collector_rows(set_name.upper(), entries, match_source=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
