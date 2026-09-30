"""TCGplayer price data via tcgcsv.com (free daily mirror, no auth).

Endpoints used:
    https://tcgcsv.com/tcgplayer/{category}/{group}/products
    https://tcgcsv.com/tcgplayer/{category}/{group}/prices

Star Wars: Unlimited is category 79. Each set is a "group"; list them with:
    curl https://tcgcsv.com/tcgplayer/79/groups
"""

import requests

CATEGORY_ID = 79  # Star Wars: Unlimited
BASE_URL = 'https://tcgcsv.com/tcgplayer'

# TCGplayer (groupId, display name) for each supported set abbreviation.
# Add new sets once TCGplayer creates their groups
# (list groups with: curl https://tcgcsv.com/tcgplayer/79/groups).
GROUPS = {
    'sor': (23405, 'Spark of Rebellion'),
    'shd': (23488, 'Shadows of the Galaxy'),
    'twi': (23597, 'Twilight of the Republic'),
    'jtl': (23956, 'Jump to Lightspeed'),
    'lof': (24279, 'Legends of the Force'),
    'ibh': (24386, 'Intro Battle: Hoth'),
    'sec': (24387, 'Secrets of Power'),
    'law': (24572, 'A Lawless Time'),
    'ash': (24660, 'Ashes of the Empire'),
    'hmw': (24812, 'Homeworlds'),
    'ic27': (24888, 'Icons 2027 Edition'),
    'ts26': (24622, 'Twin Suns'),
    # TCGplayer has two groups abbreviated P26; this one holds the TS26
    # leader showcases (prize wall, 133-140). The other, 'Sector and Regional
    # Promos: Season 2' (24854), isn't needed yet.
    'p26': (24784, 'Galactic Championship 2026'),
    # swu-db's P25 cards live in TCGplayer's catch-all Organized Play Promos
    # group; only used for SOR's Luke / Vader showcases (73, 74)
    'p25': (23455, 'Organized Play Promos'),
}


def get_set_display_name(set_name):
    """Full TCGplayer set name for an abbreviation, or the abbreviation itself."""
    group = GROUPS.get(set_name.lower())
    return group[1] if group else set_name.upper()


# Corrections for TCGplayer data errors: productId -> actual card number.
NUMBER_FIXES = {
    697960: 3,   # ASH Baylan Skoll 'Power Beyond Dream': mislabeled 4/264,
                 # colliding with Thrawn (the real 4/264); swu-db has it at 003
    679521: 56,  # TS26 Galactic Escalation: mislabeled 58/64 (Backed by the
                 # Pykes' number); swu-db has it at 056
    679523: 63,  # TS26 Rex's DC-17s: mislabeled 83/64 (Take Aim's number);
                 # swu-db has it at 063
    646496: 73,  # P25 Luke Skywalker 'Faithful Friend' showcase: mislabeled 72
                 # (Kylo Ren's number) in Organized Play Promos; swu-db has 73
    646497: 74,  # P25 Darth Vader 'Dark Lord of the Sith' showcase: mislabeled
                 # 73; swu-db has 74
}

# tcgcsv.com returns 401 for the default python-requests user agent
REQUEST_HEADERS = {'User-Agent': 'swu-tools/1.0 (SWU inventory scripts)'}


def _fetch_results(endpoint, timeout=30):
    """Fetch one tcgcsv endpoint and return its 'results' list."""
    response = requests.get(f'{BASE_URL}/{endpoint}',
                            headers=REQUEST_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()['results']


def _front_name(product_name):
    """Card name with back-side ('// Shield') and finish ('(Gold)')
    qualifiers stripped, for telling variants of one card apart from
    two different cards sharing a number."""
    name = product_name.split(' // ')[0]
    while name.endswith(')') and ' (' in name:
        name = name[:name.rindex(' (')]
    return name


def _card_number(product):
    """Extract the numeric card number from a product's extendedData.

    TCGplayer numbers cards as '015/264' (base set) or plain '295'
    (variants above the printed count). Returns an int, or None for
    non-card products such as sealed boosters.
    """
    fix = NUMBER_FIXES.get(product['productId'])
    if fix is not None:
        return fix
    for entry in product.get('extendedData', []):
        if entry['name'] == 'Number':
            try:
                return int(entry['value'].split('/')[0])
            except ValueError:
                return None
    return None


def _fetch_group_data(set_name, timeout=30):
    """Fetch a set's products and per-product price rows from tcgcsv.

    Returns (products, prices_by_product) where prices_by_product maps
    productId -> {subTypeName: price_row} (subTypeName is 'Normal' or
    'Foil'). Returns None on network failure or unknown set.
    """
    set_name = set_name.lower()
    group = GROUPS.get(set_name)
    if group is None:
        print(f"No TCGplayer group known for {set_name.upper()}. "
              f"Known sets: {', '.join(sorted(GROUPS))}")
        return None
    group_id = group[0]

    try:
        products = _fetch_results(f'{CATEGORY_ID}/{group_id}/products', timeout)
        prices = _fetch_results(f'{CATEGORY_ID}/{group_id}/prices', timeout)
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"Error: Could not fetch TCGplayer prices for {set_name.upper()}: {e}")
        return None

    by_product = {}
    for row in prices:
        by_product.setdefault(row['productId'], {})[row['subTypeName']] = row
    return products, by_product


def get_price_map(set_name, timeout=30):
    """Get TCGplayer prices for a set, keyed by 3-digit card number.

    Returns {'001': {'name': ..., 'market': float|None, 'low': float|None}, ...}
    using the Normal (non-foil) printing, falling back to Foil for
    foil-only products. Returns None on network failure or unknown set.
    """
    data = _fetch_group_data(set_name, timeout)
    if data is None:
        return None
    products, by_product = data

    price_map = {}
    for product in products:
        number = _card_number(product)
        if number is None:
            continue
        printings = by_product.get(product['productId'], {})
        price = printings.get('Normal') or printings.get('Foil')
        if price is None:
            continue
        # Variants of one card (back sides of double-sided bases, serialized
        # finishes) legitimately share a number; only a different card name
        # signals a TCGplayer data error (e.g. Baylan Skoll mislabeled with
        # Thrawn's number in ASH).
        existing = price_map.get(f'{number:03d}')
        if (existing is not None
                and _front_name(existing['name'])
                != _front_name(product['name'])):
            print(f"Warning: TCGplayer lists two products as card {number:03d} "
                  f"in {set_name.upper()}: '{existing['name']}' and "
                  f"'{product['name']}' — keeping the latter. If it's a "
                  f"TCGplayer data error, add the productId to "
                  f"tcgcsv.NUMBER_FIXES.")
        price_map[f'{number:03d}'] = {
            'name': product['name'],
            'market': price.get('marketPrice'),
            'low': price.get('lowPrice'),
        }

    print(f"{set_name.upper()} prices retrieved from tcgcsv.com "
          f"({len(price_map)} cards)")
    return price_map


def get_variant_list(set_name, tag, timeout=30):
    """Get a set's variant printings matching a TCGplayer name tag.

    tag is the parenthesized qualifier in the product name, e.g.
    '(Showcase)', '(Prestige)', or '(Prestige Foil)' — matching is exact
    including the closing paren, so '(Prestige)' does not match
    '(Prestige Foil)' products. Returns a list sorted by card number:
    [{'number': '771', 'name': 'Jyn Erso - Time to Fight',
      'product_id': int, 'market': float|None, 'low': float|None}, ...]
    Returns None on network failure or unknown set.
    """
    data = _fetch_group_data(set_name, timeout)
    if data is None:
        return None
    products, by_product = data

    variants = []
    for product in products:
        if tag not in product['name']:
            continue
        number = _card_number(product)
        if number is None:
            continue
        printings = by_product.get(product['productId'], {})
        price = printings.get('Foil') or printings.get('Normal') or {}
        variants.append({
            'number': f'{number:03d}',
            'name': product['name'].replace(tag, '').strip(),
            'product_id': product['productId'],
            'market': price.get('marketPrice'),
            'low': price.get('lowPrice'),
        })

    variants.sort(key=lambda s: s['number'])
    return variants


def get_cards_by_number(set_name, numbers, timeout=30):
    """Get specific cards of a set by number, preferring the Foil price.

    For foil-only printings (showcases) that TCGplayer doesn't tag in the
    product name, e.g. the P26 prize wall leaders. Sellers list some of
    these under Normal too, so Normal is used only when Foil has no market
    price. Same entry shape as get_variant_list, with the product name
    minus its '(Prize Wall)'-style qualifiers. Returns None on failure.
    """
    data = _fetch_group_data(set_name, timeout)
    if data is None:
        return None
    products, by_product = data
    wanted = {int(n) for n in numbers}

    cards = []
    for product in products:
        number = _card_number(product)
        if number not in wanted:
            continue
        printings = by_product.get(product['productId'], {})
        foil = printings.get('Foil') or {}
        price = foil if foil.get('marketPrice') is not None else (
            printings.get('Normal') or foil)
        cards.append({
            'number': f'{number:03d}',
            'name': _front_name(product['name']),
            'product_id': product['productId'],
            'market': price.get('marketPrice'),
            'low': price.get('lowPrice'),
        })

    cards.sort(key=lambda c: c['number'])
    return cards


def get_showcase_list(set_name, timeout=30):
    """Get the showcase (collector leader) variants of a set with prices.

    Showcase printings are foil-only. See get_variant_list for the shape.
    """
    return get_variant_list(set_name, '(Showcase)', timeout)


# TCGplayer's own marketplace search API (not tcgcsv). Answers plain
# requests as of 2026-07; if it starts blocking again, callers degrade
# gracefully since get_listing_counts returns None on any failure.
LISTINGS_URL = 'https://mp-search-api.tcgplayer.com/v1/product/{product_id}/listings'
BROWSER_USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/126.0.0.0 Safari/537.36')


def get_listing_counts(product_id, timeout=15):
    """Live market availability for one product from tcgplayer.com.

    Returns {'listings': int, 'copies': int} — the number of active seller
    listings and the total copies across them — or None on any failure.
    One POST per product; don't hammer this in large loops.
    """
    payload = {
        'filters': {
            'term': {'sellerStatus': 'Live', 'channelId': 0},
            'range': {'quantity': {'gte': 1}},
            'exclude': {'channelExclusion': 0},
        },
        'from': 0,
        'size': 1,
        'sort': {'field': 'price+shipping', 'order': 'asc'},
        'context': {'shippingCountry': 'US'},
        'aggregations': ['quantity'],
    }
    try:
        response = requests.post(
            LISTINGS_URL.format(product_id=product_id), json=payload,
            headers={'User-Agent': BROWSER_USER_AGENT}, timeout=timeout)
        response.raise_for_status()
        result = response.json()['results'][0]
        buckets = result.get('aggregations', {}).get('quantity', [])
        return {
            'listings': int(result['totalResults']),
            'copies': sum(int(b['value']) * int(b['count']) for b in buckets),
        }
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None
