import datetime as dt
import json
import os

import pandas as pd
import requests

# Main booster / premier-legal sets in release order. IBH (Intro Battle: Hoth,
# Oct 2025) is a supplemental product but is Premier- and Twin-Suns-legal, so
# it lives here rather than in SPECIAL_SETS.
MAIN_SETS = ['sor', 'shd', 'twi', 'jtl', 'lof', 'ibh', 'sec', 'law']

# Supplemental product set codes (legal in Twin Suns / Eternal only)
SPECIAL_SETS = ['ts26']

# Supported set abbreviations for card lookups
VALID_SETS = MAIN_SETS + SPECIAL_SETS

# Uppercase versions for scripts that work with SWUDB deck/set identifiers
MAIN_SETS_UPPER = [set_name.upper() for set_name in MAIN_SETS]
SPECIAL_SETS_UPPER = [set_name.upper() for set_name in SPECIAL_SETS]
VALID_SETS_UPPER = [set_name.upper() for set_name in VALID_SETS]

# Directory for cached card data
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'card_data')

# Threshold (in card count) above which a parent-less set is considered a
# "main" release rather than a promo / convention / store-showdown product.
# Captures main booster sets (~250+ cards), TS26 (84), and IBH (104); excludes
# promo bundles (≤48 cards).
MAIN_SET_CARD_THRESHOLD = 80

# ===== Format legality =====
#
# Edit the four PREMIER_* sets below when sets release, rotate, or are
# announced. Eternal and Twin Suns currently have no bans and no rotation, so
# they are not configured per-set; everything in /sets is legal there.
# Promo/OP-set parent inheritance and the pre-release auto-flip are derived by
# set_legality() from the /sets catalog and today's date.

# Currently Premier-legal main sets. Update on rotation events.
PREMIER_LEGAL_MAIN_SETS = {"JTL", "LOF", "IBH", "SEC", "LAW"}

# Upcoming sets that auto-flip Premier-legal at (release_date - PRERELEASE_DAYS).
# After release, optionally move to PREMIER_LEGAL_MAIN_SETS for clarity.
PREMIER_PENDING_SETS = {"ASH"}

# Sets explicitly rotated out of Premier (legal in Eternal / Twin Suns only).
PREMIER_ROTATED_SETS = {"SOR", "SHD", "TWI"}

# Main-class sets that are never Premier-legal (currently TS26 — Twin-Suns-only).
PREMIER_EXCLUDED_SETS = {"TS26"}

# Days before release that pre-release events make a pending set Premier-legal.
PRERELEASE_DAYS = 7

# Card-name bans in Premier (independent of set legality).
PREMIER_SUSPENDED_CARDS = {
    "Boba Fett - Collecting the Bounty",
    "Triple Dark Raid",
    "Jango Fett - Concealing the Conspiracy",
    "DJ - Blatant Thief",
    "Force Throw",
}

# On-disk cache of the /sets payload — keeps validator runs offline-capable.
SETS_CATALOG_PATH = os.path.join(CACHE_DIR, '_sets.json')


def fetch_remote_sets(timeout=30):
    """Fetch the full set catalog from the SWUDB API.

    Returns a list of dicts with keys like setId, parentSetId, numberCards,
    fullName, releaseDate. Raises requests.RequestException on network errors.
    """
    response = requests.get('https://api.swu-db.com/sets', timeout=timeout)
    response.raise_for_status()
    return response.json()


def is_main_set(set_info):
    """Heuristic for whether a /sets entry is a main release vs. a promo."""
    if set_info.get('parentSetId'):
        return False
    return (set_info.get('numberCards') or 0) >= MAIN_SET_CARD_THRESHOLD


def parse_release_date(raw):
    """Parse the SWUDB API's 'M/D/YY' release date format. Returns date or None."""
    if not raw:
        return None
    try:
        month, day, year = (int(x) for x in raw.split('/'))
        return dt.date(2000 + year, month, day)
    except (ValueError, AttributeError):
        return None


def get_sets_catalog(force_refresh=False):
    """Return the /sets payload, caching to card_data/_sets.json.

    On a clean clone, the first call hits the API and writes the cache; later
    calls (and offline runs) read the cache. Pass force_refresh=True to update.
    Returns [] if both the cache and the live API are unavailable.
    """
    if not force_refresh and os.path.exists(SETS_CATALOG_PATH):
        try:
            with open(SETS_CATALOG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass  # fall through to live fetch

    try:
        catalog = fetch_remote_sets()
    except requests.RequestException as exc:
        print(f"Warning: /sets unreachable and no cached catalog: {exc}")
        return []

    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        with open(SETS_CATALOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(catalog, f, indent=2)
    except IOError as exc:
        print(f"Warning: could not write sets catalog cache: {exc}")
    return catalog


def set_legality(set_id, catalog, today=None):
    """Return {'premier': bool, 'eternal': bool, 'twin_suns': bool} for set_id.

    Logic:
        - Eternal and Twin Suns: every set is legal (no current rotation or bans).
        - Premier: legal if the set's effective parent (parentSetId or self) is
          in PREMIER_LEGAL_MAIN_SETS, OR is in PREMIER_PENDING_SETS and today
          is within PRERELEASE_DAYS of that parent's release date.
        - Unknown sets (not in catalog): assumed Premier-illegal, Eternal/TS legal.
    """
    today = today or dt.date.today()
    info = next((s for s in catalog if s.get('setId') == set_id), None)
    if info is None:
        return {'premier': False, 'eternal': True, 'twin_suns': True}

    effective_parent = info.get('parentSetId') or set_id

    if effective_parent in PREMIER_EXCLUDED_SETS or effective_parent in PREMIER_ROTATED_SETS:
        premier = False
    elif effective_parent in PREMIER_LEGAL_MAIN_SETS:
        premier = True
    elif effective_parent in PREMIER_PENDING_SETS:
        parent_info = next((s for s in catalog if s.get('setId') == effective_parent), info)
        release = parse_release_date(parent_info.get('releaseDate'))
        premier = bool(release and today >= release - dt.timedelta(days=PRERELEASE_DAYS))
    else:
        premier = False

    return {'premier': premier, 'eternal': True, 'twin_suns': True}


def get_cache_path(set_name):
    """Get the path to the cached JSON file for a set."""
    return os.path.join(CACHE_DIR, f'{set_name.lower()}.json')


def load_from_cache(set_name):
    """Load card data from local cache if available."""
    cache_path = get_cache_path(set_name)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"{set_name.upper()} Card List Loaded from cache")
            return pd.DataFrame(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load cache for {set_name.upper()}: {e}")
    return None


def save_to_cache(set_name, data):
    """Save card data to local cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = get_cache_path(set_name)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"{set_name.upper()} Card List Saved to cache")
    except IOError as e:
        print(f"Warning: Could not save cache for {set_name.upper()}: {e}")


def get_swu_list(set_name, force_refresh=False, allow_unknown=False):
    """
    Get card list for a set. Checks local cache first, then fetches from API.

    Args:
        set_name: Set abbreviation (e.g. sor, shd, twi, jtl, lof, ibh, sec, law, ts26)
        force_refresh: If True, skip cache and fetch from API
        allow_unknown: If True, skip the VALID_SETS check and attempt the fetch
            anyway. Use for refresh-only callers that have already validated the
            setId against the SWUDB /sets catalog. Downstream scripts that key
            off VALID_SETS will not recognize the resulting cache file.

    Returns:
        DataFrame with card data, or None if failed
    """
    set_name = set_name.lower()

    if not allow_unknown and set_name not in VALID_SETS:
        print(f"Invalid set: {set_name}. Valid sets: {', '.join(VALID_SETS)}")
        return None

    # Check cache first (unless force refresh)
    if not force_refresh:
        cached_df = load_from_cache(set_name)
        if cached_df is not None:
            return cached_df

    # Fetch from API
    url = f'https://api.swu-db.com/cards/{set_name}'
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        set_json = response.json()
        card_data = set_json.get('data', [])

        if not card_data:
            print(f"Warning: No card data returned for {set_name.upper()}")
            return None

        print(f"{set_name.upper()} Card List Retrieved from API")

        # Save to cache
        save_to_cache(set_name, card_data)

        return pd.DataFrame(card_data)

    except requests.Timeout:
        print(f"Error: Request timed out for {set_name.upper()}")
        return None
    except requests.RequestException as e:
        print(f"Error: Could not fetch {set_name.upper()} from API: {e}")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error: Invalid response for {set_name.upper()}: {e}")
        return None

def get_card_name(list_df, num):
# Returns the string of card name in a card list
    match = list_df[list_df['Number'] == num]
    if not match.empty:
        name = str(list_df[list_df['Number'] == num].iloc[0]['Name'])
        # print(f"Card {num}: {name}")
    else:
        name = ""

    return name


def get_card_rarity(list_df, num):
# Returns the string of card rarity in a card list
    match = list_df[list_df['Number'] == num]
    if not match.empty:
        rarity = str(list_df[list_df['Number'] == num].iloc[0]['Rarity'])
        # print(f"Card {num}: {name}")
    else:
        rarity = ""
    return rarity[:1]

def get_card(list_df, num):
    match = list_df[list_df['Number'] == num]
    if not match.empty:
        card = list_df[list_df['Number'] == num].iloc[0]
    else:
        card = "Not Found"
    print(card)
