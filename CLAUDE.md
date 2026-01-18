# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python tools for managing Star Wars Unlimited (SWU) trading card inventory in Google Sheets. Fetches card data from the swu-db.com API and updates Google Sheets with card names and rarities.

## Commands

```bash
# Install dependencies
uv sync

# Run the main inventory updater (updates card names/rarities in Google Sheets)
uv run python main.py

# Run the extras inventory updater (separate spreadsheet for extra cards)
uv run python update_extras.py

# Run card lookup utility
uv run python lookup_card.py

# Sort a deck list by set (for gathering cards from binders)
uv run python sort_deck_by_set.py "swudb_lists/deck-Picklist.txt"

# Import and sort a deck directly from SWUDB URL
uv run python sort_deck_by_set.py "https://www.swudb.com/deck/RawKbHItN"

# Import with custom output directory
uv run python sort_deck_by_set.py "https://www.swudb.com/deck/RawKbHItN" /path/to/output

# Track cards in use across multiple decks
uv run python update_used_card_list.py add "https://www.swudb.com/deck/RawKbHItN"
uv run python update_used_card_list.py remove "https://www.swudb.com/deck/RawKbHItN"
uv run python update_used_card_list.py list
uv run python update_used_card_list.py export

# Lint with ruff
uv run ruff check .
```

## Architecture

- **main.py / update_extras.py**: Entry points that update Google Sheets. Both share similar structure but target different spreadsheets ("SWU Sets Inventory" vs "SWU Sets Extra Inventory"). Update one set at a time to avoid Google API rate limits.

- **lib/swudb.py**: API client for swu-db.com with local caching. Key functions:
  - `get_swu_list(set_name, force_refresh=False)`: Gets all cards for a set, checks local cache first then API. Use `force_refresh=True` to bypass cache.
  - `get_card_name(df, num)`: Returns card name by 3-digit number
  - `get_card_rarity(df, num)`: Returns first letter of rarity

- **card_data/**: Local JSON cache for card data (one file per set). Checked before making API calls. Data is stable after set release so this is tracked in git.

- **credentials.json**: Google API service account credentials (required for Google Sheets access)

- **sort_deck_by_set.py**: Deck list sorter for gathering cards from set-organized binders
  - Parses Picklist (.txt), JSON (.json) deck exports, or imports directly from SWUDB deck URLs
  - Groups cards by set, sorted by card number within each set
  - Prefers main sets (SOR, SHD, TWI, JTL, LOF, SEC) over promo sets for reprints
  - Shows "(also in: X, Y)" for cards printed in multiple sets
  - Outputs to console and saves sorted markdown file
  - URL imports save to `swudb_lists/` by default (uses deck name from website)
  - Optional second argument specifies custom output directory

- **update_used_card_list.py**: Track cards in use across multiple SWUDB decks
  - Maintains SQLite database at `card_data/cards_in_use.db`
  - Exports markdown summary to `swudb_lists/cards_in_use.md`
  - Commands: `add <url>`, `remove <url>`, `list`, `export`
  - Tracks deck format: Premier (deckFormat=1) or Twin Suns (deckFormat=2)
  - Cards identified by canonical (primary_set, primary_number) tuple
  - Tracks use_count per card - incremented on add, decremented on remove
  - Cards with use_count=0 are automatically removed from database

## Google Sheets Structure

The inventory spreadsheets expect:
- Each set has its own tab named by abbreviation (SOR, SHD, TWI, JTL, LOF, SEC)
- Cell H1: Total card count for the set
- Column B (starting B3): Card names
- Column D (starting D3): Card rarities (single letter)

## API and Caching Notes

- SWUDB API endpoint pattern: `https://api.swu-db.com/cards/{set_abbr}`
- Card numbers are 3-digit zero-padded strings (e.g., "001", "042")
- Card data is cached locally in `card_data/*.json` - scripts check cache before hitting API
- To refresh cached data (e.g., after errata): use `get_swu_list(set_name, force_refresh=True)`
- Google API has rate limits; run one set at a time when updating
