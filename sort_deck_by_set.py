import sys
import os
import json
import re
from collections import defaultdict
from urllib.parse import urlparse
import requests
from lib.swudb import MAIN_SETS_UPPER, SPECIAL_SETS_UPPER, VALID_SETS_UPPER

# Ordered sets for output. Main sets stay first; supplemental sets follow.
ORDERED_SETS = MAIN_SETS_UPPER + SPECIAL_SETS_UPPER

# Deck format mapping
DECK_FORMATS = {
    1: 'Premier',
    2: 'Twin Suns'
}

# Default output directory for URL imports
DEFAULT_OUTPUT_DIR = 'swudb_lists'

# Cache for API card data by set
_set_cache = {}


def get_card_name_from_api(set_abbr, card_num):
    """Look up card name from swudb API."""
    set_lower = set_abbr.lower()

    if set_abbr not in VALID_SETS_UPPER:
        return None

    # Check cache first
    if set_lower not in _set_cache:
        try:
            url = f'https://api.swu-db.com/cards/{set_lower}'
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                # Build lookup dict by card number
                _set_cache[set_lower] = {
                    card['Number']: card['Name']
                    for card in data.get('data', [])
                }
                print(f"Fetched {set_abbr} card data from API")
            else:
                _set_cache[set_lower] = {}
        except Exception as e:
            print(f"Warning: Could not fetch {set_abbr} data: {e}")
            _set_cache[set_lower] = {}

    # Look up the card
    return _set_cache.get(set_lower, {}).get(card_num)

def merge_cards_by_printing(cards):
    """Merge rows with the same (set, number); sum quantity; preserve first-seen order."""
    buckets = {}
    order = []
    for card in cards:
        key = (card['set'], card['number'])
        qty = card.get('quantity', 1)
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 1
        if qty <= 0:
            continue
        if key not in buckets:
            buckets[key] = {
                'name': card['name'],
                'set': card['set'],
                'number': card['number'],
                'alternates': list(card.get('alternates', [])),
                'quantity': qty,
            }
            order.append(key)
        else:
            buckets[key]['quantity'] += qty
            seen = set(buckets[key]['alternates'])
            for alt in card.get('alternates', []):
                if alt not in seen:
                    buckets[key]['alternates'].append(alt)
                    seen.add(alt)
    return [buckets[k] for k in order]


def item_quantity(item):
    """Read quantity from a deck JSON item (count / quantity), default 1."""
    for key in ('count', 'quantity'):
        if key in item and item[key] is not None:
            try:
                q = int(item[key])
                return max(q, 0)
            except (TypeError, ValueError):
                break
    return 1


def parse_picklist(filepath):
    """Parse a Picklist format file and return (cards, metadata)."""
    cards = []

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Card name lines start with [ ]
        if line.startswith('[ ]'):
            # Extract card name (remove the checkbox prefix)
            name = line[3:].strip()

            # Next line should have set codes
            if i + 1 < len(lines):
                set_line = lines[i + 1].strip()
                # Skip if it's another card or section marker
                if set_line and not set_line.startswith('[ ]') and not set_line.startswith('-----'):
                    set_codes = parse_set_codes(set_line)
                    if set_codes:
                        # Prefer main sets over promos
                        primary_set, primary_num = select_primary_set(set_codes)
                        # Get unique alternate sets (excluding primary set)
                        alternate_sets = list(dict.fromkeys(
                            s for s, n in set_codes if s != primary_set
                        ))
                        cards.append({
                            'name': name,
                            'set': primary_set,
                            'number': primary_num,
                            'alternates': alternate_sets,
                            'quantity': 1,
                        })
                    i += 1  # Skip the set codes line
        i += 1

    # Picklist files don't have deck metadata - use filename as title
    metadata = {
        'title': os.path.splitext(os.path.basename(filepath))[0],
        'author': None,
        'format': None,
        'leader': None,
        'second_leader': None,
        'base': None
    }

    if metadata['format'] != 'Twin Suns':
        cards = merge_cards_by_printing(cards)

    return cards, metadata


def parse_set_codes(line):
    """Parse a line of set codes like 'SEC 018, SEC 282, P25 130'."""
    codes = []
    # Match patterns like "SEC 018" or "SOROP 10"
    pattern = r'([A-Z0-9]+)\s+(\d+)'
    matches = re.findall(pattern, line)
    for set_abbr, num in matches:
        codes.append((set_abbr, num.zfill(3)))  # Zero-pad to 3 digits
    return codes


def select_primary_set(set_codes):
    """Select the primary set, preferring main sets over promos."""
    # First, look for a main set
    for set_abbr, num in set_codes:
        if set_abbr in MAIN_SETS_UPPER:
            return (set_abbr, num)

    # Then prefer known supplemental product sets over promos
    for set_abbr, num in set_codes:
        if set_abbr in SPECIAL_SETS_UPPER:
            return (set_abbr, num)

    # Fall back to first listed if no main set found
    return set_codes[0]


def parse_card_id(card_id):
    """Parse a card ID like 'SEC_018' and return card info dict."""
    parts = card_id.split('_')
    if len(parts) == 2:
        set_abbr, num = parts
        num_padded = num.zfill(3)
        # Look up card name from API
        name = get_card_name_from_api(set_abbr, num_padded)
        if not name:
            name = f"[{card_id}]"  # Fallback if API lookup fails
        return {
            'name': name,
            'set': set_abbr,
            'number': num_padded,
            'alternates': [],
            'quantity': 1,
        }
    return None


def parse_json(filepath):
    """Parse a JSON format deck file and return (cards, metadata)."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cards = []

    # Extract metadata from file
    file_metadata = data.get('metadata', {})
    has_second_leader = 'secondleader' in data and data['secondleader']

    # Parse leader, second leader, and base for metadata
    leader_info = None
    second_leader_info = None
    base_info = None

    if 'leader' in data and data['leader'] and 'id' in data['leader']:
        leader_info = parse_card_id(data['leader']['id'])
    if has_second_leader and 'id' in data['secondleader']:
        second_leader_info = parse_card_id(data['secondleader']['id'])
    if 'base' in data and data['base'] and 'id' in data['base']:
        base_info = parse_card_id(data['base']['id'])

    # Build metadata dict
    metadata = {
        'title': file_metadata.get('name', os.path.splitext(os.path.basename(filepath))[0]),
        'author': file_metadata.get('author'),
        'format': 'Twin Suns' if has_second_leader else 'Premier',
        'leader': leader_info,
        'second_leader': second_leader_info,
        'base': base_info
    }

    # Collect all card entries from different sections
    sections = ['leader', 'secondleader', 'base', 'deck', 'sideboard']
    for section in sections:
        if section not in data:
            continue

        items = data[section]
        # Handle single item (leader/base) vs list (deck)
        if isinstance(items, dict):
            items = [items]

        for item in items:
            if not item or 'id' not in item:
                continue
            card_info = parse_card_id(item['id'])
            if card_info:
                q = item_quantity(item)
                if q <= 0:
                    continue
                entry = {**card_info, 'quantity': q}
                cards.append(entry)

    if metadata['format'] != 'Twin Suns':
        cards = merge_cards_by_printing(cards)

    return cards, metadata


def is_swudb_url(input_str):
    """Check if input is a SWUDB deck URL."""
    try:
        parsed = urlparse(input_str)
        return parsed.netloc in ('swudb.com', 'www.swudb.com') and '/deck/' in parsed.path
    except Exception:
        return False


def extract_deck_id(url):
    """Extract deck ID from SWUDB URL."""
    # URL format: https://www.swudb.com/deck/RawKbHItN
    parsed = urlparse(url)
    path_parts = parsed.path.strip('/').split('/')
    if len(path_parts) >= 2 and path_parts[0] == 'deck':
        return path_parts[1]
    return None


def fetch_deck_from_url(url):
    """Fetch deck data from SWUDB URL and return (cards, metadata)."""
    deck_id = extract_deck_id(url)
    if not deck_id:
        print(f"Error: Could not extract deck ID from URL: {url}")
        return None, None

    api_url = f"https://www.swudb.com/api/deck/{deck_id}"
    print(f"Fetching deck from: {api_url}")

    try:
        response = requests.get(api_url, timeout=30)
        if response.status_code != 200:
            print(f"Error: Failed to fetch deck (status {response.status_code})")
            return None, None

        data = response.json()
        cards, metadata = parse_swudb_json(data, deck_id)
        if metadata is not None:
            metadata = {**metadata, 'source_url': url}
        return cards, metadata

    except Exception as e:
        print(f"Error fetching deck: {e}")
        return None, None


def format_card_name(card_data):
    """Format card name with title if present."""
    name = card_data.get('cardName', '')
    title = card_data.get('title', '')
    if title:
        return f"{name} - {title}"
    return name


def extract_card_info(card_data):
    """Extract card info dict from SWUDB card data."""
    if not card_data:
        return None
    name = format_card_name(card_data)
    set_abbr = card_data.get('defaultExpansionAbbreviation', '')
    num = card_data.get('defaultCardNumber', '').zfill(3)
    if name and set_abbr:
        return {
            'name': name,
            'set': set_abbr,
            'number': num,
            'alternates': [],
            'quantity': 1,
        }
    return None


def parse_swudb_json(data, deck_id):
    """Parse SWUDB JSON response to extract cards and deck metadata."""
    deck_format_code = data.get('deckFormat', 1)
    metadata = {
        'title': data.get('deckName', deck_id),
        'author': data.get('authorName'),
        'format': DECK_FORMATS.get(deck_format_code, 'Unknown'),
        'leader': extract_card_info(data.get('leader')),
        'second_leader': extract_card_info(data.get('secondLeader')),
        'base': extract_card_info(data.get('base'))
    }

    card_counts = {}

    def add_card(card_data, qty=1):
        if not card_data or qty <= 0:
            return
        info = extract_card_info(card_data)
        if not info:
            return
        key = (info['set'], info['number'])
        if key in card_counts:
            card_counts[key]['quantity'] += qty
        else:
            card_counts[key] = {**info, 'quantity': qty}

    add_card(data.get('leader'), 1)
    add_card(data.get('secondLeader'), 1)
    add_card(data.get('base'), 1)

    for entry in data.get('shuffledDeck', []):
        card_data = entry.get('card')
        if not card_data:
            continue
        main_count = entry.get('count', 0) or 0
        sideboard_count = entry.get('sideboardCount', 0) or 0
        total = main_count + sideboard_count
        if total > 0:
            add_card(card_data, total)

    cards = list(card_counts.values())
    return cards, metadata


def group_by_set(cards):
    """Group cards by set and sort by card number within each set."""
    grouped = defaultdict(list)
    for card in cards:
        grouped[card['set']].append(card)

    # Sort cards within each set by number
    for set_abbr in grouped:
        grouped[set_abbr].sort(key=lambda c: c['number'])

    return grouped


def format_card_reference(card_info):
    """Format a card reference like 'Card Name (SET 001)'."""
    if not card_info:
        return None
    return f"{card_info['name']} ({card_info['set']} {card_info['number']})"


def format_header(metadata):
    """Format deck metadata as a markdown header."""
    lines = []

    # Title
    lines.append(f"# {metadata['title']}")
    lines.append("")

    # Format, source URL (URL imports), and Author
    info_lines = []
    if metadata.get('format'):
        info_lines.append(f"**Format:** {metadata['format']}")
    if metadata.get('source_url'):
        src = metadata['source_url']
        info_lines.append(f"**Source:** [{src}]({src})")
    if metadata.get('author'):
        info_lines.append(f"**Author:** {metadata['author']}")

    if info_lines:
        lines.append("  \n".join(info_lines))
        lines.append("")

    # Leader(s) and Base
    card_lines = []
    if metadata.get('leader'):
        card_lines.append(f"**Leader:** {format_card_reference(metadata['leader'])}")
    if metadata.get('second_leader'):
        card_lines.append(f"**Leader 2:** {format_card_reference(metadata['second_leader'])}")
    if metadata.get('base'):
        card_lines.append(f"**Base:** {format_card_reference(metadata['base'])}")

    if card_lines:
        lines.append("  \n".join(card_lines))
        lines.append("")

    # Separator
    lines.append("---")

    return '\n'.join(lines)


def format_output(grouped, metadata=None):
    """Format grouped cards as markdown output with optional header."""
    lines = []

    # Add header if metadata is provided
    if metadata:
        lines.append(format_header(metadata))

    # Sort sets: main sets first in order, then promo/special sets alphabetically
    all_sets = list(grouped.keys())
    known_sets = [s for s in ORDERED_SETS if s in all_sets]
    unknown_sets = sorted([s for s in all_sets if s not in ORDERED_SETS])
    ordered_sets = known_sets + unknown_sets

    show_qty_suffix = (metadata or {}).get('format') != 'Twin Suns'

    for set_abbr in ordered_sets:
        cards = grouped[set_abbr]
        total_qty = sum(c.get('quantity', 1) for c in cards)
        lines.append(f"\n## {set_abbr} ({total_qty} CARDS)")

        for card in cards:
            line = f"- {card['number']}: {card['name']}"
            if show_qty_suffix and card.get('quantity', 1) > 1:
                line += f" ×{card['quantity']}"
            if card['alternates']:
                line += f" (also in: {', '.join(card['alternates'])})"
            lines.append(line)

    return '\n'.join(lines)


def detect_format(filepath):
    """Detect file format based on extension and content."""
    if filepath.endswith('.json'):
        return 'json'
    return 'picklist'


def get_output_path(filepath):
    """Generate output markdown path: same folder, same name with '-sorted.md'."""
    directory = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    # Remove extension
    name_without_ext = os.path.splitext(basename)[0]
    # Create new filename with -sorted.md
    output_name = f"{name_without_ext}-sorted.md"
    return os.path.join(directory, output_name)


def get_url_output_path(deck_name, output_dir=None):
    """Generate output path for URL-imported decks."""
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Sanitize deck name for filename
    safe_name = re.sub(r'[^\w\s-]', '', deck_name).strip()
    safe_name = re.sub(r'[-\s]+', '-', safe_name)

    return os.path.join(output_dir, f"{safe_name}-sorted.md")


def main():
    if len(sys.argv) < 2:
        print("Usage: python sort_deck_by_set.py <deck_file_or_url> [output_dir]")
        print("  Supports: Picklist (.txt), JSON (.json), or SWUDB deck URL")
        print("  Example URL: https://www.swudb.com/deck/RawKbHItN")
        sys.exit(1)

    input_arg = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    # Check if input is a URL
    if is_swudb_url(input_arg):
        cards, metadata = fetch_deck_from_url(input_arg)
        if not cards:
            print("No cards found from URL.")
            sys.exit(1)
        output_path = get_url_output_path(metadata['title'], output_dir)
    else:
        # File-based input
        filepath = input_arg
        file_format = detect_format(filepath)

        if file_format == 'json':
            cards, metadata = parse_json(filepath)
        else:
            cards, metadata = parse_picklist(filepath)

        if not cards:
            print("No cards found in file.")
            sys.exit(1)

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            basename = os.path.basename(filepath)
            name_without_ext = os.path.splitext(basename)[0]
            output_path = os.path.join(output_dir, f"{name_without_ext}-sorted.md")
        else:
            output_path = get_output_path(filepath)

    grouped = group_by_set(cards)
    output = format_output(grouped, metadata)

    # Print to console
    print(output)

    # Write to markdown file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output.lstrip('\n'))  # Remove leading newline
    print(f"\nSaved to: {output_path}")


if __name__ == '__main__':
    main()
