"""Show TCGplayer prices for showcase variants (collector leader printings).

Every main set has one showcase printing per leader (foil-only). A few
leader showcases were printed in yearly promo sets instead (PROMO_SHOWCASES):
SOR's Luke / Vader in P25 and the TS26 pre-con leaders in P26. They list with
Source "P25 Showcase" / "P26 Showcase" and the original set's number. By default
this prints a per-set price list to console. With --update-sheet it also
writes the list to the "Collector" tab of the inventory spreadsheet,
preserving the hand-entered Count column and any rows it doesn't manage
(rows are matched by Card Num. + Source).

The console list includes live market availability (copies / listings)
fetched per-card from tcgplayer.com; pass --no-listings to skip that for
a faster, prices-only run.

Usage:
    uv run python showcase_prices.py                 # all main sets, console only
    uv run python showcase_prices.py law ash         # specific sets
    uv run python showcase_prices.py p25 p26         # promo-set showcases (SOR Luke/Vader, TS26 leaders; 'ts26' = p26)
    uv run python showcase_prices.py --no-listings   # skip availability lookups
    uv run python showcase_prices.py --update-sheet  # also update the Collector tab
"""

import sys

import lib.swudb as swudb
import lib.tcgcsv as tcgcsv
from main import get_doc_sheet

COLLECTOR_TAB = 'Collector'
HEADER_ROWS = 2  # row 1 title, row 2 column headers; data starts at row 3
# Collector tab columns: A Card Num., B Card Name, C Count,
# D Original Card Number, E Source, F Current Price
COL_NUM, COL_NAME, COL_COUNT, COL_ORIGINAL, COL_SOURCE, COL_PRICE = range(6)

# Leader showcases printed in yearly promo sets instead of their own set:
# promo set -> set holding the originals. Both are swu-db set ids; the promo
# set also needs a tcgcsv.GROUPS entry for its TCGplayer group.
#   P25: SOR's ultra-rare Luke / Vader showcases (not in TCGplayer's SOR group)
#   P26: the TS26 pre-con leaders' prize wall showcases
PROMO_SHOWCASES = {'p25': 'sor', 'p26': 'ts26'}


def original_card_number(set_df, variant_number):
    """Map a variant printing's number to the card's original number.

    swu-db lists every printing of a card (base / hyperspace / showcase /
    prestige) as its own row sharing Name+Subtitle; the lowest number is
    the original. Works for any card type, not just leaders.
    Returns '' when the variant isn't in the set data.
    """
    if set_df is None:
        return ''
    match = set_df[set_df['Number'] == variant_number]
    if match.empty:
        return ''
    card = match.iloc[0]
    # NaN is truthy, so `or ''` won't normalize a missing subtitle —
    # non-leader cards usually have none
    subtitle = card['Subtitle'] if isinstance(card['Subtitle'], str) else ''
    same = set_df[(set_df['Name'] == card['Name'])
                  & (set_df['Subtitle'].fillna('') == subtitle)]
    # Numbers are strings and variant numbers can be 4 digits (JTL 1028+),
    # so a plain min() would compare lexicographically ('1028' < '104')
    return min(same['Number'], key=int)


def collect_promo_showcases(promo_set):
    """Leader showcases from a promo set (see PROMO_SHOWCASES).

    TCGplayer doesn't tag these '(Showcase)', so they're found in swu-db's
    promo set (Leader + VariantType Showcase) and matched to their original
    by Name+Subtitle; prices come from TCGplayer by promo card number.
    Returns a list of entries like collect_showcases, or None on failure.
    """
    original_set = PROMO_SHOWCASES[promo_set]
    promo_df = swudb.get_swu_list(promo_set, allow_unknown=True)
    original_df = swudb.get_swu_list(original_set)
    if promo_df is None or original_df is None:
        return None

    def card_key(card):
        subtitle = card['Subtitle'] if isinstance(card['Subtitle'], str) else ''
        return card['Name'], subtitle

    # Sub set caches store unpadded numbers ('8'); pad to match the sheet
    leaders = {card_key(card): str(card['Number']).zfill(3)
               for _, card in original_df[original_df['Type'] == 'Leader'].iterrows()}
    showcases = promo_df[(promo_df['Type'] == 'Leader')
                         & (promo_df['VariantType'] == 'Showcase')]
    originals = {str(card['Number']).zfill(3): leaders[card_key(card)]
                 for _, card in showcases.iterrows()
                 if card_key(card) in leaders}
    if not originals:
        print(f'Skipping {promo_set.upper()}: no {original_set.upper()} '
              f'leader showcases found')
        return None

    entries = tcgcsv.get_cards_by_number(promo_set, originals)
    if entries is None:
        return None
    for entry in entries:
        entry['original'] = originals[entry['number']]
    missing = sorted(set(originals) - {e['number'] for e in entries})
    if missing:
        print(f"Warning: {promo_set.upper()} showcases not on TCGplayer: "
              f"{', '.join(missing)}")
    return entries


def collect_showcases(set_names):
    """Fetch showcase price lists per set. Returns {set_name: [entries]}.

    Each entry gains an 'original' key with the base leader's card number.
    Sets with no showcase products (e.g. IBH) are skipped with a note.
    """
    results = {}
    for set_name in set_names:
        set_name = set_name.lower()
        if set_name == 'ts26':
            set_name = 'p26'  # TS26's only showcases are the P26 prize wall ones
        if set_name in PROMO_SHOWCASES:
            showcases = collect_promo_showcases(set_name)
            if showcases:
                results[set_name] = showcases
            continue
        if set_name not in tcgcsv.GROUPS:
            print(f'Skipping {set_name.upper()}: no TCGplayer group known')
            continue
        showcases = tcgcsv.get_showcase_list(set_name)
        if showcases is None:
            continue
        if not showcases:
            print(f'Skipping {set_name.upper()}: no showcase cards found')
            continue
        set_df = swudb.get_swu_list(set_name)
        for entry in showcases:
            entry['original'] = original_card_number(set_df, entry['number'])
        if any(not entry['original'] for entry in showcases):
            # A cache written before a set's variants were published lacks
            # the showcase numbers — refresh once and retry the mapping
            set_df = swudb.get_swu_list(set_name, force_refresh=True)
            for entry in showcases:
                entry['original'] = original_card_number(set_df, entry['number'])
        results[set_name] = showcases
    return results


def format_money(value):
    return f'${value:,.2f}' if value is not None else '   n/a'


def fetch_listing_stats(showcases_by_set):
    """Add live market availability to each showcase (entry['stock']).

    One request per card against tcgplayer.com itself. Gives up for the
    rest of the run after 3 consecutive failures so a re-blocked API
    doesn't stall every remaining card on its timeout.
    """
    total = sum(len(s) for s in showcases_by_set.values())
    print(f'Fetching live listing counts from tcgplayer.com ({total} cards)...')
    consecutive_failures = 0
    for showcases in showcases_by_set.values():
        for s in showcases:
            if consecutive_failures >= 3:
                s['stock'] = None
                continue
            s['stock'] = tcgcsv.get_listing_counts(s['product_id'])
            consecutive_failures = 0 if s['stock'] else consecutive_failures + 1
    if consecutive_failures >= 3:
        print('  listing counts unavailable (tcgplayer.com not answering) '
              '— showing prices only')


def format_stock(stock):
    if stock is None:
        return 'avail      n/a'
    return f"avail {stock['copies']:>3} in {stock['listings']:>2} listings"


def print_showcases(showcases_by_set, with_stock):
    for set_name, showcases in showcases_by_set.items():
        market_total = sum(s['market'] or 0 for s in showcases)
        print(f'\n=== {set_name.upper()} — {tcgcsv.get_set_display_name(set_name)} '
              f'({len(showcases)} showcases) ===')
        for s in showcases:
            original = f"(base {s['original']})" if s['original'] else '(base ???)'
            stock = f"  {format_stock(s.get('stock'))}" if with_stock else ''
            print(f"  {s['number']}  {s['name']:<45.45} {original:>10}  "
                  f"market {format_money(s['market']):>10}  "
                  f"low {format_money(s['low']):>10}{stock}")
        print(f'  set total: market {format_money(market_total)}')


def upsert_collector_rows(tab_name, entries, match_source=True):
    """Write rows to a Collector-layout tab, preserving unmanaged data.

    entries are dicts with number, name, original, source, market. Existing
    rows are matched by (Card Num., Source) — or Card Num. alone when
    match_source is False, for tabs holding a single set — and updated in
    place; the Count column and any rows this script doesn't manage are
    untouched. New entries are appended after the last used row. Reads
    formulas (not rendered values) so writing the region back doesn't
    flatten them.
    """
    sheet = get_doc_sheet(tab_name)
    rows = sheet.get_values(f'A{HEADER_ROWS + 1}:F',
                            value_render_option='FORMULA')
    # Normalize to 6 columns so in-place updates can't index past a short row
    rows = [row + [''] * (6 - len(row)) for row in rows]

    def norm(num):
        # Card numbers can read back as 771, '771, or 010 — compare loosely
        return str(num).strip().lstrip("'").lstrip('0')

    def key(num, source):
        return (norm(num), str(source).strip()) if match_source else norm(num)

    index = {key(row[COL_NUM], row[COL_SOURCE]): i
             for i, row in enumerate(rows) if str(row[COL_NUM]).strip()}

    updated = appended = 0
    for e in entries:
        price = e['market'] if e['market'] is not None else ''
        # Leading apostrophes keep 3-digit numbers as text in Sheets
        original = f"'{e['original']}" if e['original'] else ''
        i = index.get(key(e['number'], e['source']))
        if i is not None:
            rows[i][COL_NAME] = e['name']
            rows[i][COL_ORIGINAL] = original
            rows[i][COL_SOURCE] = e['source']
            rows[i][COL_PRICE] = price
            updated += 1
        else:
            rows.append([f"'{e['number']}", e['name'], '',
                         original, e['source'], price])
            appended += 1

    last_row = HEADER_ROWS + len(rows)
    sheet.update(rows, f'A{HEADER_ROWS + 1}:F{last_row}',
                 value_input_option='USER_ENTERED')
    sheet.format(f'F{HEADER_ROWS + 1}:F{last_row}',
                 {'numberFormat': {'type': 'CURRENCY', 'pattern': '$0.00'}})
    print(f'\n{tab_name} tab updated: {appended} rows added, '
          f'{updated} prices refreshed')


def update_collector_sheet(showcases_by_set):
    """Write showcase rows to the Collector tab (Source 'LAW Showcase').

    Original Card Number carries the set abbreviation ('LAW 045'); promo
    showcases name the set holding the original ('P26 Showcase' -> 'TS26 001').
    """
    entries = []
    for set_name, showcases in showcases_by_set.items():
        original_set = PROMO_SHOWCASES.get(set_name, set_name).upper()
        for s in showcases:
            original = f"{original_set} {s['original']}" if s['original'] else ''
            entries.append(dict(s, source=f'{set_name.upper()} Showcase',
                                original=original))
    upsert_collector_rows(COLLECTOR_TAB, entries)


if __name__ == '__main__':
    args = sys.argv[1:]
    update_sheet = '--update-sheet' in args
    if update_sheet:
        args.remove('--update-sheet')
    with_stock = '--no-listings' not in args
    if not with_stock:
        args.remove('--no-listings')

    set_names = args or [s for s in swudb.MAIN_SETS if s in tcgcsv.GROUPS] + list(PROMO_SHOWCASES)
    showcases_by_set = collect_showcases(set_names)
    if not showcases_by_set:
        print('No showcase data found.')
        sys.exit(1)

    if with_stock:
        fetch_listing_stats(showcases_by_set)
    print_showcases(showcases_by_set, with_stock)
    if update_sheet:
        update_collector_sheet(showcases_by_set)
