# Star Wars Unlimited(SWU) Tools
Scripts to manage descriptions and meta data for my card list inventory in google sheets

## Local Setup
- Install Python, UV
- Run `uv sync` to install python libraries needed.

## Set Up in Google Docs:
- Go into googles api, you need to enable google drive, docs, and sheets api
- Create an api service account, done in the api.
- Share the google sheet you want modified with the service account, give them full editor rights
- Add credentials for the service account and api urls in your credentials.json file 
 
Note: If you are not sure how to do this. ChatGPT generated a step by step how-to for this, the prompt I used was "How do I edit a google doc sheet with python?"

## Files
- `main.py` will download card lists as json from a swudb api into a pandas dataframe. It then will pull cards names and rarity into the columns I specify.
- `./lib/swudb.py` library functions to pull card lists based on set abbreviation name `SOR, SHD, TWI, JTL, LOF, SEC, LAW`, plus `TS26` for Twin Suns 2026 deck cards
- `./card_data/` cached JSON files for each set (loaded before hitting the API)
- `lookup_card.py` Start of a card lookup script, should pull all info of a card based on set and card number and print it to console.
- `sort_deck_by_set.py` Takes a deck list and outputs cards sorted by set. Useful for gathering cards from binders organized by set.
- `update_used_card_list.py` Builds a card-usage SQLite database and per-deck summary report from a text file of SWUDB deck URLs (one grouping per list file).
- `find_card.py` Looks up which tracked decks use a card (`find_card.py ash 199`) across all grouping databases, plus the owned count from the inventory snapshot.
- `sync_inventory.py` Snapshots the inventory sheet's owned counts into `card_data/inventory.db` so lookups don't need the Google Sheets API.
- `validate_deck_format.py` Fetches a SWUDB deck, detects whether it is Premier-style or Twin Suns, and reports legality for Premier, Eternal, and Twin Suns.
- `trilogy_validator.py` Validates three SWU decks together as a Premier Trilogy or Twin Suns Trilogy Gauntlet build (distinct leaders/bases + combined-copy limit).
- `deck_diff.py` Shows a GitHub-style diff of two decks (added / removed cards) for deckbuilding iteration.
- `refresh_cache.py` Downloads / refreshes `card_data/` from the SWUDB API. Run with no arguments to refresh every known set, or pass set abbreviations (e.g. `law ts26`) to refresh specific ones. Use `--list` to see main sets + cache dates (warns when a new main release appears in the API but isn't in `VALID_SETS`), or `--list-all` to include promo / OP / convention sets.
- `export_website_data.py` Exports the `card_data/` cache as pruned per-set JSON (+ `index.json`) for the swudecktools website (`../swudecktools/website/public/data/` by default). Run after `refresh_cache.py` whenever set data changes.
- `build_ts26_decks.py` Regenerates `card_data/ts26_decks.json` (the TS26 card → pre-con deck mapping) from a CSV export of the "TS Pre-Con Deck Breakdown" sheet.
- `./card_data/ts26_decks.json` Hand-maintained mapping of each TS26 card number to the pre-constructed Twin Suns deck(s) it appears in. Unlike the rest of `card_data/`, this file is committed (the SWUDB API has no deck-origin field).
- `./lib/deck_source.py` Unified loader that returns a normalized deck from a SWUDB URL, `.json`, `.txt` picklist, or sorted `.md` file.
- `./lib/tcgcsv.py` TCGplayer price data via tcgcsv.com (free daily mirror, no API key). Maps each set abbreviation to its TCGplayer group and returns market/low prices keyed by 3-digit card number.
- `update_prices.py` Writes TCGplayer Market/Low prices into columns H/I of a set's inventory tab.
- `generate_buy_list.py` Scans the inventory tabs for cards short of a full playset (3 copies) and writes a priced `buy_list.txt`.
- `showcase_prices.py` Prints TCGplayer prices for every set's showcase (collector leader) variants; `--update-sheet` also writes them to the Collector tab.
- `prestige_prices.py` Prints TCGplayer prices for prestige variants (normal + foil tiers; serialized excluded). `--mark-sheet` bold-borders the column E cell of every prestige-printing card on the set tabs.

**Note on private decks:** The SWUDB deck API only serves **Public** or **Unlisted** decks. A Private deck still renders in the browser but returns 404 from the API. Every deck-fetching script (`sort_deck_by_set.py`, `update_used_card_list.py`, `validate_deck_format.py`, `trilogy_validator.py`, `deck_diff.py`) prints a hint suggesting you change visibility to Unlisted when it sees a 404.

## Deck Sorting Tool
The `sort_deck_by_set.py` script helps gather cards for a deck from set-organized binders.

**Usage:**
```bash
uv run python sort_deck_by_set.py "path/to/decklist.txt"
```

**Features:**
- Supports Picklist (.txt) and JSON (.json) deck formats from swudb.com
- Groups cards by set (SOR, SHD, TWI, JTL, LOF, SEC, LAW, then TS26), sorted by card number
- Prefers main sets over promo printings for cards in multiple sets
- Shows alternate sets for reprints (e.g., "also in: P25, LOFP")
- Tags TS26 cards with the pre-con deck(s) they came from (e.g., `[from: Blood Brothers]`), since TS26 cards exist only in the four pre-constructed Twin Suns decks and not in any collectable set. A card shared across multiple pre-cons lists each one. Sourced from `card_data/ts26_decks.json`.
- Outputs to console and saves a `-sorted.md` file in the same folder

**Input formats:**
- Picklist format: Export from swudb.com deck builder (has card names + all set printings)
- JSON format: Export from swudb.com (has set/number, card names fetched via API)

## Deck Group Tracker

The `update_used_card_list.py` script builds a card-usage database and summary report from a list of SWUDB deck URLs. Each list file is its own grouping (e.g. one for Twin Suns decks, one for Premier decks).

**Usage:**
```bash
uv run python update_used_card_list.py swudb_lists/twin_suns_lists.md
```

The input file has one SWUDB deck URL per line — plain URLs or markdown bullets like `- [Name](https://swudb.com/deck/...)` both work. Blank lines and `#` comments are skipped.

**Outputs** (named after the input file):
- `card_data/<stem>.db` — SQLite database of the decks and every card they use (main + sideboard)
- `<input dir>/<stem>-report.md` — per-deck summary table: name, format, leaders, base, aspects, card count (no full card lists)

Each run rebuilds the grouping from scratch, so edit the list file and re-run to stay in sync.

**Format detection:** SWUDB has no Eternal format code (its enum is 1=Premier, 2=Twin Suns, 3=Trilogy) — Eternal decks are saved as Premier. Decks saved as Premier are therefore classified by legality: Premier-legal → `Premier`, otherwise Eternal-legal → `Eternal`, otherwise `Premier (illegal)`.

## Card Finder

The `find_card.py` script answers "which of my decks is this card in?" across every grouping database.

**Usage:**
```bash
uv run python find_card.py ash 199                    # set + number
uv run python find_card.py law 117 --db premier_lists # one grouping only
uv run python find_card.py --list                     # show available databases
```

**Output:**
```
LAW 117: Conveyex Security Captain
Inventory: 4 in binder; extras (if any) in bulk/trade boxes (synced 2026-07-22 23:25)

premier_lists:
  DJ +10,000 IQ Combo v7.12 (Premier) — 2 side

twin_suns_lists:
  TS - You are mine now. (Twin Suns) — 1 main

Total copies in use: 3
```

## Inventory Snapshot

`sync_inventory.py` copies the spreadsheet's owned counts (column C of each set tab) into `card_data/inventory.db`, so `find_card.py` can show what you own without hitting the Google Sheets API.

```bash
uv run python sync_inventory.py            # every set tab
uv run python sync_inventory.py law ash    # specific sets
```

**Count semantics:** the sheet tracks copies stored in the collection binders, up to a playset of 4. A count under 4 means that's every copy and it's in the binder; 4+ means the binder playset is full and any extras live (untracked) in the bulk/trade boxes. Blank cells mean the card isn't tracked. Re-run after updating counts in the sheet — `find_card.py` shows the sync date so stale data is visible.

**Variant codes (column E):** hand-entered codes track owned variant printings — `P1` non-foil prestige, `P2` foil prestige, `P3(serial)` serialized (e.g. `1xP3(127/250)`), `S` showcase, plus assorted judge/prize codes. The sync stores them and `find_card.py` decodes the known ones:

```
LOF 234: Darth Malak - Covetous Apprentice
Inventory: 3 in binder (synced 2026-07-22 23:47)
Variants owned: 2× Prestige Foil, 1× Serialized (127/250)
```

`update_prices.py` also stamps each set tab with a "Prices Updated:" timestamp in J1/K1, which the sync copies into the snapshot.

## Deck Format Validator

The `validate_deck_format.py` script checks a SWUDB deck URL against the current sourced rules for Premier, Eternal, and Twin Suns.

**Usage:**
```bash
uv run python validate_deck_format.py "https://swudb.com/deck/KRvnhNGlV"
```

**Features:**
- Detects whether the submitted deck is `Premier-style constructed` or `Twin Suns`
- Reports `VALID` or `INVALID` for Premier, Eternal, and Twin Suns
- Explains why a deck fails a format check
- Uses the centralized format-legality model in `lib/swudb.py`: current Premier rotation, pre-release auto-flip for pending sets, promo / OP / prerelease parent inheritance, and the Premier-suspended card list. See **Maintaining set and format legality** below for how to update these as sets release or rotate.

**Current limitations:**
- Reprint legality is currently resolved by full printed card name from the sourced card data
- Premier suspension checks are the only suspension checks currently applied

## Trilogy Validator

The `trilogy_validator.py` script validates three SWU decks together as a Trilogy build. It auto-detects whether the three decks are Premier-style (3-copy combined limit) or Twin Suns (1-copy combined limit, the unofficial *Twin Suns Trilogy Gauntlet* community format).

**Usage:**
```bash
uv run python trilogy_validator.py <deck1> <deck2> <deck3>
```

Each `<deck>` may be a SWUDB URL, a `.json` deck export, a `.txt` picklist, or a sorted `.md` file produced by `sort_deck_by_set.py`.

**Checks per deck:** runs the existing Premier or Twin Suns validation. When the source isn't a URL, aspect / `alternativeDeckMaximum` / suspended-name checks are skipped (with a printed note).

**Cross-deck checks:**
- All leaders distinct across the three decks (no leader may repeat in any slot).
- All three bases distinct.
- Combined-copy limit: 3 for Premier Trilogy, 1 for Twin Suns Trilogy Gauntlet.

**Search a plain text deck list (`--lists FILE`):**
```bash
uv run python trilogy_validator.py --lists swudb_lists/twin_suns_lists.txt
```
Pass a plain text file with one deck source per line. Blank lines and `#` comments are ignored. Each source may be a SWUDB URL, `.json`, `.txt`, or sorted `.md` deck file.

**Search a markdown deck list (`--mdlists FILE`):**
```bash
uv run python trilogy_validator.py --mdlists swudb_lists/twin_suns_lists.md
```
Pass a markdown file with `- [Name](URL)` lines (one deck per bullet). In both list modes, the validator searches every combination of 3 for a valid Trilogy. If none qualify, it reports the closest combination — the one with no duplicate leaders/bases and the fewest cards over the combined-copy limit — and prints the specific shared cards.

## Deck Diff

The `deck_diff.py` script prints a GitHub-style diff between two decks — useful when iterating on a list and you want to know exactly which cards to pull and which to add.

**Usage:**
```bash
uv run python deck_diff.py <old_deck> <new_deck>
```

Each argument may be a SWUDB URL, `.json`, `.txt`, or sorted `.md` file. Cards are matched by `(set, number)`, so a reprint swap (same name, different set) reads as one removal + one addition. Sections covered: leaders, base, main deck, sideboard. Sideboard is folded into the main deck for the diff when either source is a non-URL file (because picklist/markdown formats don't carry sideboard separately).

## Google Sheet Inventory
How I set up my inventory. I set up my functions in `main.py` with this format in mind.
- I have one google sheet with my inventory, and separate sheet tabs for each set each named by set abbreviation.
- In cell H1 of every tab I have the card count for that set(listed here: 'https://swudb.com/sets').
- The card names are Column B starting at cell B3
- Card rarities are column D starting at D3
- Owned-copy counts are column C starting at C3 (used by `generate_buy_list.py`)
- TCGplayer prices are columns H (Market) and I (Low) starting at row 3, written by `update_prices.py`
![Sheet Example](images/sheet-example.png)

## Card Prices & Buy List

Prices come from [tcgcsv.com](https://tcgcsv.com), a free daily mirror of TCGplayer pricing (no API key needed). Both scripts use the Normal (non-foil) printing of each card.

**Write prices onto a set's inventory tab (columns H/I):**
```bash
uv run python update_prices.py ash        # one set
uv run python update_prices.py law sec    # several sets in one run
```

**Generate a buy list of cards short of a full playset (3 copies):**
```bash
uv run python generate_buy_list.py               # every set tab in the sheet
uv run python generate_buy_list.py law ash       # specific sets
uv run python generate_buy_list.py --all         # include leaders and bases
uv run python generate_buy_list.py -o wants.txt  # custom output file
```

The buy list (`buy_list.txt` by default) shows how many copies are needed per card with market/low prices, per-set subtotals, and a grand total. Leaders and bases are excluded by default (card types come from the cached swu-db set data); pass `--all` to include them. A blank Count cell means the card isn't tracked and is ignored — enter an explicit `0` for a wanted card you own none of. Cards without a TCGplayer price yet (common during presale) show `n/a` and are excluded from totals — this can make a presale set's low total exceed its market total, since more cards have listing prices than sale-history prices.

New sets need their TCGplayer group id added to `GROUPS` in `lib/tcgcsv.py` (list groups with `curl https://tcgcsv.com/tcgplayer/79/groups`).

## Showcase Prices

Showcases are the foil-only collector printing of each leader (one per leader per set). `showcase_prices.py` prints a per-set price list and can maintain the **Collector** tab of the inventory sheet.

```bash
uv run python showcase_prices.py                 # all main sets, console only
uv run python showcase_prices.py law ash         # specific sets
uv run python showcase_prices.py --no-listings   # skip availability lookups (faster)
uv run python showcase_prices.py --update-sheet  # also update the Collector tab
```

Each line shows the showcase's card number, the leader, the original (base) card number, market/low prices, and live market availability (`avail 4 in 3 listings` = 4 copies across 3 seller listings). Availability comes from TCGplayer's own marketplace API — one request per card, so pass `--no-listings` for a faster prices-only run; if TCGplayer starts blocking, the script degrades to prices-only automatically. The base number comes from matching the showcase's number into the swu-db set data (every printing of a leader is its own row there; the lowest number is the original) — if the local cache predates a set's variant data, the script refreshes it automatically.

`--update-sheet` fills the Collector tab columns: Card Num., Card Name, Count (hand-entered, never touched), Original Card Number, Source (`LAW Showcase`), Current Price (market). Rows are matched by Card Num. + Source, so reruns refresh prices in place, new sets append, and any other rows on the tab are left alone.

Note: SOR has only 16 priceable showcases — the ultra-rare Luke Skywalker "Faithful Friend" and Darth Vader "Dark Lord of the Sith" showcases are not cataloged as TCGplayer products.

## Notes:
- The google api only supports so many actions per minute, so if you want to add and retrieve data from your sheet keep that in mind. This is why I gather a list data struct and push the whole list to the sheet at once when updating the rename column.
- When I run this to update card names I will do one set list at a time to make sure I do not hit the google actions limit.

## Maintaining set and format legality

All set lists and format-legality rules live in **`lib/swudb.py`**. The `refresh_cache.py --list` command surfaces what needs updating with `⚠` warnings at the bottom of its output.

### Configuration knobs

Six constants you'll edit over time, all near the top of `lib/swudb.py`:

```python
MAIN_SETS               = ['sor', 'shd', 'twi', 'jtl', 'lof', 'ibh', 'sec', 'law']
SPECIAL_SETS            = ['ts26']
PREMIER_LEGAL_MAIN_SETS = {"JTL", "LOF", "IBH", "SEC", "LAW"}
PREMIER_PENDING_SETS    = {"ASH"}        # auto-flips Premier-legal at release - 7 days
PREMIER_ROTATED_SETS    = {"SOR", "SHD", "TWI"}
PREMIER_EXCLUDED_SETS   = {"TS26"}       # main-class but never Premier-legal
PREMIER_SUSPENDED_CARDS = {...}          # card-name bans, independent of set legality
```

Everything else — Eternal and Twin Suns legality (currently no rotation or bans), promo / OP / prerelease parent inheritance, and the pre-release auto-flip — is derived automatically by `set_legality()` from the `/sets` API catalog and today's date.

`MAIN_SETS` / `SPECIAL_SETS` lowercase entries drive cache file naming and the `VALID_SETS` allowlist used by `refresh_cache.py`. The four `PREMIER_*` sets drive what `validate_deck_format.py` accepts.

### Common scenarios

**A new main set gets announced (e.g., Home Worlds).** Wait until the set ID appears in the SWUDB API (`refresh_cache.py --list` will warn "Main-class set(s) not in VALID_SETS"). Then:
1. Add the lowercase set ID to `MAIN_SETS` in release-date order.
2. Add the uppercase ID to `PREMIER_PENDING_SETS`.

**A pending set passes its pre-release threshold (e.g., `ASH` on 2026-07-20).** No action required — `set_legality()` auto-flips it Premier-legal. As a one-line cleanup, move the ID from `PREMIER_PENDING_SETS` to `PREMIER_LEGAL_MAIN_SETS` so the data matches reality.

**A set rotates out of Premier.** Move the ID from `PREMIER_LEGAL_MAIN_SETS` to `PREMIER_ROTATED_SETS`. Cards from that set still pass Premier validation if their name appears in any set still in `PREMIER_LEGAL_MAIN_SETS` (the reprint rule).

**A reprint set drops (speculated *Icons*).** Add its ID to both `MAIN_SETS` and `PREMIER_LEGAL_MAIN_SETS`. The reprint-name logic in `validate_deck_format.py` automatically re-enables any same-named rotated cards in Premier.

**A supplemental set is Twin-Suns / Eternal only (like `TS26`).** Add the lowercase ID to `SPECIAL_SETS` and the uppercase ID to `PREMIER_EXCLUDED_SETS`.

**Promo / OP / prerelease sets (`JTLOP`, `LAWOP`, `P26`, etc.).** No action needed. `set_legality()` follows `parentSetId` from `/sets` and inherits the parent's Premier legality automatically.

**Cards get suspended or unsuspended in Premier.** Edit `PREMIER_SUSPENDED_CARDS` in `lib/swudb.py`.

### Sanity-checking your changes

```bash
uv run python refresh_cache.py --list
```

The output's `prem` / `etrn` / `TS` columns show current per-set legality. `*` marks pending sets (with the flip date in the fullName column); `(rotated)` annotates rotated sets. Warnings at the bottom surface:
- Main-class sets newly visible in `/sets` but not in `VALID_SETS`
- Sets in `VALID_SETS` without any `PREMIER_*` assignment
- Local cache files for sets the API no longer recognizes
