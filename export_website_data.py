"""Export pruned per-set card data for the swudecktools website.

Reads the local card_data/ cache (refresh first with refresh_cache.py) and
writes space-efficient JSON the website can serve as static assets:

    <out>/<code>.json   one file per set, all printings, pruned fields
    <out>/index.json    set list with counts + generated date (staleness check)

Usage:
    uv run python export_website_data.py             # export every cached set
    uv run python export_website_data.py law ts26    # export specific sets
    uv run python export_website_data.py --out PATH  # default: ../swudecktools/website/public/data
"""

import argparse
import datetime as dt
import json
import os
import sys

from lib.swudb import VALID_SETS, get_cache_path

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'swudecktools', 'website', 'public', 'data'
)

# Card fields the website consumes. Everything else (rules text, prices,
# artist, art URLs) is dropped — art is fetched from swudb at runtime.
def prune_card(card):
    out = {
        'number': card.get('Number'),
        'name': card.get('Name'),
        'type': card.get('Type'),
    }
    if card.get('Subtitle'):
        out['subtitle'] = card['Subtitle']
    if card.get('Aspects'):
        out['aspects'] = card['Aspects']
    if card.get('Rarity'):
        out['rarity'] = card['Rarity']
    if card.get('Unique'):
        out['unique'] = True
    if card.get('Cost') not in (None, ''):
        out['cost'] = card['Cost']
    if card.get('VariantType') and card['VariantType'] != 'Normal':
        out['variant'] = card['VariantType']
    return out


def load_cached_rows(set_id):
    path = get_cache_path(set_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('data', data) if isinstance(data, dict) else data


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sets', nargs='*', help='set codes to export (default: all cached sets)')
    parser.add_argument('--out', default=DEFAULT_OUT, help='output directory')
    args = parser.parse_args()

    targets = [s.lower() for s in args.sets] if args.sets else VALID_SETS
    os.makedirs(args.out, exist_ok=True)

    index_path = os.path.join(args.out, 'index.json')
    index = {'generated': dt.date.today().isoformat(), 'sets': {}}
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                prior = json.load(f)
            index['sets'] = prior.get('sets', {})
        except (json.JSONDecodeError, IOError):
            pass

    exported = 0
    for set_id in targets:
        rows = load_cached_rows(set_id)
        if rows is None:
            print(f"{set_id.upper()}: no cache file — skipped (run refresh_cache.py {set_id})")
            continue
        cards = [prune_card(c) for c in rows]
        base = sum(1 for c in rows if c.get('VariantType') == 'Normal')
        out_path = os.path.join(args.out, f'{set_id.lower()}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(cards, f, ensure_ascii=False, separators=(',', ':'))
        index['sets'][set_id.upper()] = {'cards': len(cards), 'base': base}
        print(f"{set_id.upper()}: {len(cards)} printings ({base} base) -> {out_path} "
              f"({os.path.getsize(out_path) // 1024} KB)")
        exported += 1

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"index.json: {len(index['sets'])} sets, generated {index['generated']}")
    return 0 if exported else 1


if __name__ == '__main__':
    sys.exit(main())
