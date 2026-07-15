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
# IC27 is not on TCGplayer yet; add it here once it gets a group.
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
    'ts26': (24622, 'Twin Suns'),
}


def get_set_display_name(set_name):
    """Full TCGplayer set name for an abbreviation, or the abbreviation itself."""
    group = GROUPS.get(set_name.lower())
    return group[1] if group else set_name.upper()


# tcgcsv.com returns 401 for the default python-requests user agent
REQUEST_HEADERS = {'User-Agent': 'swu-tools/1.0 (SWU inventory scripts)'}


def _fetch_results(endpoint, timeout=30):
    """Fetch one tcgcsv endpoint and return its 'results' list."""
    response = requests.get(f'{BASE_URL}/{endpoint}',
                            headers=REQUEST_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()['results']


def _card_number(product):
    """Extract the numeric card number from a product's extendedData.

    TCGplayer numbers cards as '015/264' (base set) or plain '295'
    (variants above the printed count). Returns an int, or None for
    non-card products such as sealed boosters.
    """
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
        price_map[f'{number:03d}'] = {
            'name': product['name'],
            'market': price.get('marketPrice'),
            'low': price.get('lowPrice'),
        }

    print(f"{set_name.upper()} prices retrieved from tcgcsv.com "
          f"({len(price_map)} cards)")
    return price_map


def get_showcase_list(set_name, timeout=30):
    """Get the showcase (collector leader) variants of a set with prices.

    Showcase products are identified by '(Showcase)' in the TCGplayer name
    and are foil-only printings. Returns a list sorted by card number:
    [{'number': '771', 'name': 'Jyn Erso - Time to Fight',
      'market': float|None, 'low': float|None}, ...]
    Returns None on network failure or unknown set.
    """
    data = _fetch_group_data(set_name, timeout)
    if data is None:
        return None
    products, by_product = data

    showcases = []
    for product in products:
        if '(Showcase)' not in product['name']:
            continue
        number = _card_number(product)
        if number is None:
            continue
        printings = by_product.get(product['productId'], {})
        price = printings.get('Foil') or printings.get('Normal') or {}
        showcases.append({
            'number': f'{number:03d}',
            'name': product['name'].replace('(Showcase)', '').strip(),
            'product_id': product['productId'],
            'market': price.get('marketPrice'),
            'low': price.get('lowPrice'),
        })

    showcases.sort(key=lambda s: s['number'])
    return showcases


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
