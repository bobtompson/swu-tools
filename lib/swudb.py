import requests
import pandas as pd
import json
import os

# Valid set abbreviations
VALID_SETS = ['sor', 'shd', 'twi', 'jtl', 'lof', 'sec']

# Directory for cached card data
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'card_data')


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


def get_swu_list(set_name, force_refresh=False):
    """
    Get card list for a set. Checks local cache first, then fetches from API.

    Args:
        set_name: Set abbreviation (sor, shd, twi, jtl, lof, sec)
        force_refresh: If True, skip cache and fetch from API

    Returns:
        DataFrame with card data, or None if failed
    """
    set_name = set_name.lower()

    if set_name not in VALID_SETS:
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
