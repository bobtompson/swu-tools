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

# Lint with ruff
uv run ruff check .
```

## Architecture

- **main.py / update_extras.py**: Entry points that update Google Sheets. Both share similar structure but target different spreadsheets ("SWU Sets Inventory" vs "SWU Sets Extra Inventory"). Update one set at a time to avoid Google API rate limits.

- **lib/swudb.py**: API client for swu-db.com. Key functions:
  - `get_swu_list(set_name)`: Fetches all cards for a set (sor, shd, twi, jtl, lof, sec), returns DataFrame
  - `get_card_name(df, num)`: Returns card name by 3-digit number
  - `get_card_rarity(df, num)`: Returns first letter of rarity

- **credentials.json**: Google API service account credentials (required for Google Sheets access)

## Google Sheets Structure

The inventory spreadsheets expect:
- Each set has its own tab named by abbreviation (SOR, SHD, TWI, JTL, LOF, SEC)
- Cell H1: Total card count for the set
- Column B (starting B3): Card names
- Column D (starting D3): Card rarities (single letter)

## API Notes

- SWUDB API endpoint pattern: `https://api.swu-db.com/cards/{set_abbr}`
- Card numbers are 3-digit zero-padded strings (e.g., "001", "042")
- Google API has rate limits; run one set at a time when updating
