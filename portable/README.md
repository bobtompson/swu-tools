# Trilogy Validator (portable)

A self-contained tool for validating three Star Wars Unlimited decks together as a
**Trilogy** build — both the official **Premier Trilogy** and the community
**Twin Suns Trilogy Gauntlet** format. It is meant to be handed to someone (e.g. an
event judge) and run on its own; it does not need the rest of the swu-tools repo.

## What's in this folder

| File | Purpose |
|------|---------|
| `trilogy_validator.py` | The validator — a single self-contained script. |
| `requirements.txt` | The two libraries it needs (`requests`, `pandas`). |
| `card_data/` | Bundled card data for every released set, so Premier reprint checks work without internet. |

## Setup

Requires **Python 3.8+**. Install the two dependencies:

```bash
pip install -r requirements.txt
```

(If you use `uv`, `uv run --with requests --with pandas python trilogy_validator.py ...`
also works.)

## Usage

**Validate three specific decks.** Each source can be a SWUDB deck URL, or a path to a
`.json` deck export, a `.txt` picklist, or a sorted `.md` deck file:

```bash
python3 trilogy_validator.py <deck1> <deck2> <deck3>

# example — three SWUDB URLs
python3 trilogy_validator.py \
  https://www.swudb.com/deck/AAAAA \
  https://www.swudb.com/deck/BBBBB \
  https://www.swudb.com/deck/CCCCC
```

**Search a list of decks for the best Trilogy combination.** Pass a markdown file with
one `- [Name](URL)` link per line:

```bash
python3 trilogy_validator.py --lists my_decks.md
```

The format (Premier vs. Twin Suns) is auto-detected from the decks. Exit code is `0`
when the Trilogy is valid, `1` when it isn't.

## What it checks

**Premier Trilogy** — each deck must be Premier-legal (1 leader, 1 base, 50+ card deck,
≤3 copies per card, no rotated-only or suspended cards), all three leaders distinct, all
three bases distinct, and **≤3 copies of any card across all three decks combined**.

**Twin Suns Trilogy Gauntlet** — each deck must be Twin Suns-legal (2 aligned leaders,
1 base, 80+ card singleton deck), all leaders and bases distinct, and **only 1 copy of
any card across all three decks combined**.

A SWUDB URL gives the validator full card metadata. A `.json` / `.txt` / `.md` source
can't, so aspect / copy-maximum / suspended-card checks are skipped for those with a
printed note — use SWUDB URLs for a complete check.

## Note: this is a frozen snapshot

This script bundles the swu-tools validation logic as it stood when generated. The rules
it enforces (set rotation, suspended cards, the set list including `TS26`) are frozen.
If the official SWU rules change, regenerate this folder from the swu-tools repo.
