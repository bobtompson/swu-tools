"""Refresh every price on the inventory spreadsheet in one run.

Runs each pricing script's sheet update in turn:

  1. Set tabs   - TCGplayer Market/Low in columns H/I (update_prices.py)
                  for every tab named after a set in VALID_SETS
  2. Collector  - showcase prices on the Collector tab
                  (showcase_prices.py --update-sheet --no-listings)
  3. Promo tabs - promo set prices on each promo tab that exists, e.g. P26
                  (promo_prices.py <set> --update-sheet)
  4. Sealed     - booster display / Spotlight Deck prices on the Sealed tab
                  (sealed_prices.py --update-sheet)

A failure in one step is reported and the run carries on; the summary at
the end lists what succeeded, and the exit code is non-zero if anything
failed. Prices come from tcgcsv.com, which refreshes once a day.

Usage:
    uv run python update_all_prices.py
    uv run python update_all_prices.py --refresh-promos   # re-fetch promo sets from swu-db first
    uv run python update_all_prices.py --only sets sealed # run selected steps
"""

import argparse
import sys
import traceback

import lib.swudb as swudb
import lib.tcgcsv as tcgcsv
import promo_prices
import sealed_prices
import showcase_prices
from main import get_spreadsheet
from update_prices import update_prices

STEPS = ['sets', 'collector', 'promos', 'sealed']


def update_set_tabs(tab_titles):
    """Write H/I prices on every set tab. Returns the sets that failed."""
    set_names = [s for s in swudb.VALID_SETS if s.upper() in tab_titles]
    failed = []
    for set_name in set_names:
        print(f'\n--- {set_name.upper()} ---')
        if set_name not in tcgcsv.GROUPS:
            print(f'Skipping {set_name.upper()}: no TCGplayer group known')
            continue
        try:
            if not update_prices(set_name):
                failed.append(set_name.upper())
        except Exception:
            traceback.print_exc()
            failed.append(set_name.upper())
    return failed


def update_collector():
    showcase_set_names = ([s for s in swudb.MAIN_SETS if s in tcgcsv.GROUPS]
                          + list(showcase_prices.PROMO_SHOWCASES))
    showcases_by_set = showcase_prices.collect_showcases(showcase_set_names)
    if not showcases_by_set:
        raise RuntimeError('no showcase data found')
    showcase_prices.update_collector_sheet(showcases_by_set)


def update_promo_tabs(tab_titles, refresh):
    """Write each promo set that has its own tab. Returns the sets that failed."""
    failed = []
    for set_name in showcase_prices.PROMO_SHOWCASES:
        tab = set_name.upper()
        if tab not in tab_titles:
            continue
        print(f'\n--- {tab} ---')
        try:
            entries = promo_prices.collect_promos(set_name, refresh=refresh)
            if not entries:
                print(f'No card data for {tab}.')
                failed.append(tab)
                continue
            showcase_prices.upsert_collector_rows(tab, entries, match_source=False)
        except Exception:
            traceback.print_exc()
            failed.append(tab)
    return failed


def update_sealed():
    rows = sealed_prices.collect_prices(swudb.MAIN_SETS)
    if not rows:
        raise RuntimeError('no sealed product data found')
    sealed_prices.update_sheet(rows)


def run_step(title, func, *args):
    """Run one step; returns a list of failure labels (empty on success)."""
    print(f'\n===== {title} =====')
    try:
        failed = func(*args)
    except Exception:
        traceback.print_exc()
        return [title]
    return [f'{title}: {name}' for name in failed or []]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--only', nargs='+', choices=STEPS, metavar='STEP',
                        help=f"run only these steps ({', '.join(STEPS)})")
    parser.add_argument('--refresh-promos', action='store_true',
                        help='re-fetch promo sets from swu-db (new promos appear all season)')
    args = parser.parse_args()
    steps = args.only or STEPS

    tab_titles = {ws.title.upper() for ws in get_spreadsheet().worksheets()}

    failures = []
    if 'sets' in steps:
        failures += run_step('Set tabs', update_set_tabs, tab_titles)
    if 'collector' in steps:
        failures += run_step('Collector', update_collector)
    if 'promos' in steps:
        failures += run_step('Promo tabs', update_promo_tabs, tab_titles,
                             args.refresh_promos)
    if 'sealed' in steps:
        failures += run_step('Sealed', update_sealed)

    print('\n===== Summary =====')
    print(f"Steps run: {', '.join(steps)}")
    if failures:
        print('Failed:')
        for failure in failures:
            print(f'  {failure}')
        return 1
    print('All prices updated.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
