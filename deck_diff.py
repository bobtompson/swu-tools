#!/usr/bin/env python3
"""Show a GitHub-style diff between two SWU decks.

Identity is (set, number) — a card with the same name in a different set
prints as one removal + one addition (the right behaviour for "what to
pull from binders"). Quantity changes print only the difference ('+ 1x'
when a card goes from 2 to 3 copies). When both decks carry a separate
sideboard, a final Net Cards section combines main deck + sideboard so
cards that just move between them drop out. Sources may be SWUDB URLs,
.json deck exports, .txt picklists, or sorted .md files produced by
sort_deck_by_set.py; mixing types works, but any non-URL source folds the
sideboard into the main deck (those formats don't keep it separate).

Usage:
    # Two SWUDB decks (old first, new second)
    uv run python deck_diff.py https://swudb.com/deck/oDEIxoWTsm https://swudb.com/deck/YezSwWFyp

    # A saved sorted .md (from sort_deck_by_set.py) against the current online list
    uv run python deck_diff.py "swudb_lists/Boba-on-the-Lake-v73-sorted.md" https://swudb.com/deck/RawKbHItN

    # Two local exports: a .txt picklist and a .json deck export
    uv run python deck_diff.py old-Picklist.txt new-deck.json

    # Markdown output (```diff blocks that GitHub / VS Code color red and green)
    uv run python deck_diff.py <old> <new> --markdown          # print to the terminal
    uv run python deck_diff.py <old> <new> -o swudb_lists/wicket_diff.md   # write a file

    # Show this help
    uv run python deck_diff.py --help
"""

import argparse
import shlex
from pathlib import Path

import requests
from rich.console import Console

import validate_deck_format as vdf
from lib.deck_source import card_identity, load_deck

console = Console()


def _section_map(entries):
    """(set, number) -> {'qty': int, 'card': payload, 'name': str} for one section."""
    out = {}
    for entry in entries:
        card = entry["card"]
        key = card_identity(card)
        if key in out:
            out[key]["qty"] += entry["quantity"]
        else:
            out[key] = {
                "qty": entry["quantity"],
                "card": card,
                "name": vdf.format_card_name(card),
            }
    return out


def _leaders_map(leaders):
    out = {}
    for leader in leaders:
        key = card_identity(leader)
        out[key] = {
            "qty": 1,
            "card": leader,
            "name": vdf.format_card_name(leader),
        }
    return out


def _base_map(base):
    if base is None:
        return {}
    return {
        card_identity(base): {
            "qty": 1,
            "card": base,
            "name": vdf.format_card_name(base),
        }
    }


def _diff_section(old_map, new_map):
    """Return (lines, added, removed) for one section.

    Each line is (sign, qty, label, old_qty, new_qty) where qty is the number
    of copies to add ('+') or pull ('-'): a card going from 2 to 3 copies is
    a single '+ 1x' line, not a remove-all / add-all pair.
    """
    keys = sorted(set(old_map) | set(new_map))
    lines = []
    added = removed = 0
    for key in keys:
        old_entry = old_map.get(key)
        new_entry = new_map.get(key)
        old_qty = old_entry["qty"] if old_entry else 0
        new_qty = new_entry["qty"] if new_entry else 0
        delta = new_qty - old_qty
        if delta == 0:
            continue
        card = (new_entry or old_entry)["card"]
        label = vdf.card_printing_label(card)
        if delta > 0:
            lines.append(("+", delta, label, old_qty, new_qty))
            added += delta
        else:
            lines.append(("-", -delta, label, old_qty, new_qty))
            removed += -delta
    # Removals first, then additions; the sort is stable, so each group
    # keeps its (set, number) order
    lines.sort(key=lambda line: line[0] != "-")
    return lines, added, removed


def _count_note(old_qty, new_qty):
    """'2 → 3' when the card stays in the section, else '' (fully added/removed)."""
    return f"{old_qty} → {new_qty}" if old_qty and new_qty else ""


def _print_section(title, lines):
    if not lines:
        return
    console.print(f"[bold]## {title}[/bold]")
    for sign, qty, label, old_qty, new_qty in lines:
        color = "green" if sign == "+" else "red"
        note = _count_note(old_qty, new_qty)
        counts = f" [dim]({note})[/dim]" if note else ""
        console.print(f"[{color}]{sign} {qty}x {label}[/{color}]{counts}")
    console.print()


def build_diff(old_deck, new_deck):
    """Return (sections, total_added, total_removed).

    sections is a list of (title, lines) for every section with changes, in
    print order; lines come from _diff_section. Net Cards is included (but not
    counted in the totals) when both decks keep a separate sideboard.
    """
    pairs = [
        ("Leaders", _leaders_map(old_deck["leaders"]), _leaders_map(new_deck["leaders"])),
        ("Base", _base_map(old_deck["base"]), _base_map(new_deck["base"])),
    ]

    # Markdown / picklist sources flatten sideboard into the main deck. If either
    # side lacks full metadata, fold sideboards into mainboards for the diff so
    # we don't report phantom sideboard moves that are really just input-format
    # differences.
    fold_sideboard = not (
        old_deck.get("metadata_complete", False) and new_deck.get("metadata_complete", False)
    )
    old_all = _section_map(old_deck["mainboard"] + old_deck["sideboard"])
    new_all = _section_map(new_deck["mainboard"] + new_deck["sideboard"])
    if fold_sideboard:
        pairs.append(("Main Deck", old_all, new_all))
    else:
        pairs.append(("Main Deck", _section_map(old_deck["mainboard"]),
                      _section_map(new_deck["mainboard"])))
        pairs.append(("Sideboard", _section_map(old_deck["sideboard"]),
                      _section_map(new_deck["sideboard"])))

    sections = []
    total_added = total_removed = 0
    for title, old_map, new_map in pairs:
        lines, added, removed = _diff_section(old_map, new_map)
        if lines:
            sections.append((title, lines))
        total_added += added
        total_removed += removed

    if sections and not fold_sideboard:
        # Physical cards to pull / add with main deck and sideboard combined, so
        # a card that only moves between them (or partly does) nets out.
        net_lines, _, _ = _diff_section(old_all, new_all)
        if net_lines:
            sections.append(("Net Cards (main + sideboard)", net_lines))

    return sections, total_added, total_removed


def print_console(old_deck, new_deck, args, sections, total_added, total_removed):
    console.print(
        f"[bold]# Deck Diff:[/bold] "
        f"[red]{old_deck.get('title', args.old)}[/red] → "
        f"[green]{new_deck.get('title', args.new)}[/green]"
    )
    console.print(f"  [red]old:[/red] {old_deck.get('source', args.old)}")
    console.print(f"  [green]new:[/green] {new_deck.get('source', args.new)}")
    console.print()

    if not sections:
        console.print("No changes between decks.")
        return
    for title, lines in sections:
        _print_section(title, lines)
    console.print(f"Summary: [green]+{total_added}[/green], [red]-{total_removed}[/red]")


def render_markdown(old_deck, new_deck, args, sections, total_added, total_removed):
    """The diff as Markdown: each section in a ```diff fence so viewers color it."""
    command = shlex.join(["uv", "run", "python", "deck_diff.py", args.old, args.new])
    out = [
        f"# Deck Diff: {old_deck.get('title', args.old)} → {new_deck.get('title', args.new)}",
        "",
        f"- **old:** {old_deck.get('source', args.old)}",
        f"- **new:** {new_deck.get('source', args.new)}",
        "",
        "Command:",
        "",
        "```bash",
        command,
        "```",
        "",
    ]
    if not sections:
        out.append("No changes between decks.")
    else:
        for title, lines in sections:
            out += [f"## {title}", "", "```diff"]
            for sign, qty, label, old_qty, new_qty in lines:
                note = _count_note(old_qty, new_qty)
                out.append(f"{sign} {qty}x {label}" + (f" ({note})" if note else ""))
            out += ["```", ""]
        out.append(f"Summary: +{total_added}, -{total_removed}")
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("old", help="Old deck: SWUDB URL or path to .json/.txt/.md")
    parser.add_argument("new", help="New deck: SWUDB URL or path to .json/.txt/.md")
    parser.add_argument("--markdown", action="store_true",
                        help="print the diff as Markdown (```diff blocks) instead of colored text")
    parser.add_argument("-o", "--output", metavar="PATH",
                        help="write the Markdown diff to PATH instead of printing it")
    args = parser.parse_args()

    try:
        old_deck = load_deck(args.old)
        new_deck = load_deck(args.new)
    except (requests.RequestException, ValueError) as exc:
        console.print(f"[red]Error loading deck: {exc}[/red]")
        raise SystemExit(1) from exc

    diff = build_diff(old_deck, new_deck)

    if args.output:
        path = Path(args.output)
        path.write_text(render_markdown(old_deck, new_deck, args, *diff), encoding="utf-8")
        console.print(f"Saved to: {path}", soft_wrap=True)
    elif args.markdown:
        # Plain print: rich would treat [brackets] in card names as markup
        print(render_markdown(old_deck, new_deck, args, *diff), end="")
    else:
        print_console(old_deck, new_deck, args, *diff)


if __name__ == "__main__":
    main()
