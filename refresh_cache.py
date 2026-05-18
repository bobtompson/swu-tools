"""Refresh local card_data/ cache for one or more sets.

Usage:
    uv run python refresh_cache.py              # refresh every known set
    uv run python refresh_cache.py law ts26     # refresh specific sets
    uv run python refresh_cache.py --list       # list main sets + cache status
    uv run python refresh_cache.py --list-all   # list every set the API knows
"""

import argparse
import datetime as dt
import os
import sys

import requests

from lib.swudb import (
    CACHE_DIR,
    PREMIER_LEGAL_MAIN_SETS,
    PREMIER_PENDING_SETS,
    PREMIER_ROTATED_SETS,
    PRERELEASE_DAYS,
    VALID_SETS,
    VALID_SETS_UPPER,
    fetch_remote_sets,
    get_cache_path,
    get_sets_catalog,
    get_swu_list,
    is_main_set,
    parse_release_date,
    set_legality,
)


def _cache_mtime_iso(set_id):
    """Return ISO date of the local cache file for set_id, or '' if absent."""
    path = get_cache_path(set_id)
    if not os.path.exists(path):
        return ''
    return dt.date.fromtimestamp(os.path.getmtime(path)).isoformat()


def _list_local_only():
    """Fallback when /sets is unreachable: show whatever is on disk."""
    print("(Could not reach the SWUDB /sets endpoint — showing local cache only.)")
    print()
    if not os.path.isdir(CACHE_DIR):
        print("No card_data/ directory.")
        return
    rows = []
    for entry in sorted(os.listdir(CACHE_DIR)):
        if not entry.endswith('.json'):
            continue
        set_id = entry[:-5].upper()
        rows.append((set_id, _cache_mtime_iso(set_id.lower())))
    if not rows:
        print("No cached sets.")
        return
    print(f"{'setId':<8} {'cached':<12}")
    print('-' * 22)
    for set_id, cached in rows:
        print(f"{set_id:<8} {cached:<12}")


def _release_key(set_info):
    """Sort key for chronological M/D/YY release date ordering.
    Sets with no release date sort last."""
    parsed = parse_release_date(set_info.get('releaseDate'))
    if parsed is None:
        return (1, dt.date.max)
    return (0, parsed)


def _legality_cell(legal, set_id, catalog, today):
    """Render a legality column. Pending sets show '*' until their flip date."""
    if legal:
        return '✓'
    if set_id in PREMIER_PENDING_SETS:
        info = next((s for s in catalog if s.get('setId') == set_id), None)
        release = parse_release_date((info or {}).get('releaseDate'))
        if release and today < release - dt.timedelta(days=PRERELEASE_DAYS):
            return '*'
    return '-'


def _annotate_full_name(set_id, full_name, catalog, today):
    """Append legality context to a set's display name (rotated / pending date)."""
    if set_id in PREMIER_ROTATED_SETS:
        return f"{full_name} (rotated)"
    if set_id in PREMIER_PENDING_SETS:
        info = next((s for s in catalog if s.get('setId') == set_id), None)
        release = parse_release_date((info or {}).get('releaseDate'))
        if release and today < release - dt.timedelta(days=PRERELEASE_DAYS):
            flip = release - dt.timedelta(days=PRERELEASE_DAYS)
            return f"{full_name} (Premier-legal {flip.isoformat()})"
    return full_name


def _run_list(show_all):
    """Print a table of available sets, cache status, and per-format legality."""
    catalog = get_sets_catalog(force_refresh=True)
    if not catalog:
        print()
        _list_local_only()
        return

    today = dt.date.today()

    if show_all:
        filtered = sorted(
            catalog,
            key=lambda s: (s.get('parentSetId') or s.get('setId') or '',
                           s.get('setId') or ''),
        )
        header = (f"{'setId':<8} {'parent':<7} {'cards':>5}  {'release':<10}  "
                  f"{'cached':<12}  {'prem':<4} {'etrn':<4} {'TS':<3}  fullName")
        sep_len = 96
    else:
        filtered = [s for s in catalog if is_main_set(s)]
        filtered.sort(key=_release_key)
        header = (f"{'setId':<8} {'cards':>5}  {'release':<10}  {'cached':<12}  "
                  f"{'prem':<4} {'etrn':<4} {'TS':<3}  fullName")
        sep_len = 88

    print(header)
    print('-' * sep_len)
    for s in filtered:
        set_id = s.get('setId') or '?'
        cards = s.get('numberCards') or 0
        release = s.get('releaseDate') or ''
        full_name = _annotate_full_name(set_id, s.get('fullName') or '', catalog, today)
        cached = _cache_mtime_iso(set_id.lower()) if set_id != '?' else ''
        legality = set_legality(set_id, catalog, today=today)
        prem = _legality_cell(legality['premier'], set_id, catalog, today)
        etrn = '✓' if legality['eternal'] else '-'
        ts = '✓' if legality['twin_suns'] else '-'
        if show_all:
            parent = s.get('parentSetId') or ''
            print(f"{set_id:<8} {parent:<7} {cards:>5}  {release:<10}  "
                  f"{cached:<12}  {prem:<4} {etrn:<4} {ts:<3}  {full_name}")
        else:
            print(f"{set_id:<8} {cards:>5}  {release:<10}  {cached:<12}  "
                  f"{prem:<4} {etrn:<4} {ts:<3}  {full_name}")

    # Warn about main-class sets we don't yet support in VALID_SETS.
    remote_main_ids = {s.get('setId') for s in catalog if is_main_set(s)}
    new_main = sorted(remote_main_ids - set(VALID_SETS_UPPER))
    if new_main:
        print()
        print(f"⚠ Main-class set(s) not in VALID_SETS — update lib/swudb.py to support: "
              f"{', '.join(new_main)}")

    # Warn about sets in VALID_SETS with no format-legality assignment.
    assigned = (PREMIER_LEGAL_MAIN_SETS | PREMIER_PENDING_SETS
                | PREMIER_ROTATED_SETS | {'TS26'})
    unassigned = sorted(set(VALID_SETS_UPPER) - assigned)
    if unassigned:
        print()
        print(f"⚠ Set(s) in VALID_SETS without a PREMIER_* assignment in "
              f"lib/swudb.py: {', '.join(unassigned)}")

    # Warn about orphan local cache files.
    if os.path.isdir(CACHE_DIR):
        remote_all_ids = {s.get('setId') for s in catalog if s.get('setId')}
        local_ids = {
            entry[:-5].upper()
            for entry in os.listdir(CACHE_DIR)
            if entry.endswith('.json') and not entry.startswith('_')
        }
        orphans = sorted(local_ids - remote_all_ids)
        if orphans:
            print()
            print(f"Note: local cache file(s) with no matching set in /sets: "
                  f"{', '.join(orphans)}")


def _run_refresh(requested):
    # No args: refresh every set in VALID_SETS (the curated default).
    if not requested:
        targets = list(VALID_SETS)
        succeeded = 0
        for set_name in targets:
            if get_swu_list(set_name, force_refresh=True) is not None:
                succeeded += 1
        print()
        print(f"Refreshed {succeeded}/{len(targets)} sets.")
        return (0 if succeeded == len(targets) else 1), None

    # Specific sets: accept anything VALID_SETS recognizes, or anything the
    # SWUDB /sets catalog knows about (promos, OP sets, etc.). Hard-error on
    # set IDs the API itself doesn't recognize.
    normalized = [s.lower() for s in requested]
    out_of_list = [s for s in normalized if s not in VALID_SETS]
    api_ids = None
    if out_of_list:
        try:
            remote = fetch_remote_sets()
        except requests.RequestException as exc:
            return 2, (
                f"Cannot verify out-of-list set(s) {', '.join(u.upper() for u in out_of_list)}: "
                f"/sets unreachable ({exc})."
            )
        api_ids = {s.get('setId', '').lower() for s in remote if s.get('setId')}
        truly_unknown = [s for s in out_of_list if s not in api_ids]
        if truly_unknown:
            return 2, (
                f"Unknown set(s): {', '.join(u.upper() for u in truly_unknown)}. "
                f"Not in VALID_SETS and not in the SWUDB /sets catalog. "
                f"Run `refresh_cache.py --list-all` to see every set ID."
            )

    succeeded = 0
    for set_name in normalized:
        if set_name in VALID_SETS:
            ok = get_swu_list(set_name, force_refresh=True) is not None
        else:
            ok = get_swu_list(set_name, force_refresh=True, allow_unknown=True) is not None
            if ok:
                print(f"  (note: {set_name.upper()} is not in VALID_SETS — "
                      f"cache written, but downstream scripts won't recognize it)")
        if ok:
            succeeded += 1

    print()
    print(f"Refreshed {succeeded}/{len(normalized)} sets.")
    return (0 if succeeded == len(normalized) else 1), None


def main():
    parser = argparse.ArgumentParser(
        description="Refresh local card_data/ cache from the SWUDB API."
    )
    parser.add_argument(
        "sets",
        nargs="*",
        help=f"Set abbreviations to refresh (case-insensitive). "
        f"Omit to refresh every known set: {', '.join(s.upper() for s in VALID_SETS)}.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List main-class sets from the SWUDB API with local cache status; "
        "skip refresh.",
    )
    parser.add_argument(
        "--list-all",
        action="store_true",
        help="Like --list, but include promo / OP / convention / store-showdown sets.",
    )
    args = parser.parse_args()

    if args.list and args.list_all:
        parser.error("Use only one of --list or --list-all.")
    if (args.list or args.list_all) and args.sets:
        parser.error("Cannot combine --list / --list-all with set names.")

    if args.list or args.list_all:
        _run_list(show_all=args.list_all)
        sys.exit(0)

    code, err = _run_refresh(args.sets)
    if err:
        parser.error(err)
    sys.exit(code)


if __name__ == "__main__":
    main()
