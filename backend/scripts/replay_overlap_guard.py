"""Measure the proposed overlap-guard rule against real import history (read-only).

Origin of each DB row = the earliest file (by mtime) whose parsed rows hash to it.
For each file in mtime order, rows not already present from an earlier file are candidates;
they are paired against rows that came from earlier files by
app.imports.overlap.find_suspected_duplicates (the code the import uses).
See docs/lld_import_overlap_guard_claude.md.
Run from the repo root (not from backend/, to avoid triggering the dev server's reload):
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/venv/Scripts/python.exe backend/scripts/replay_overlap_guard.py 3
Needs backend/finance.db.bak-2026-10-14-pre-dedupe (the pre-dedupe snapshot; gitignored).
"""
import os, sqlite3, sys
from datetime import date
from pathlib import Path
from app.imports.registry import match, get_parser
from app.imports.base import compute_row_hashes
from app.imports.pipeline import resolve_account_definition
from app.imports.overlap import ExistingRow, NewRow, find_suspected_duplicates

WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 3
DATA = Path("C:/Projects/personalfinanceapp/data")
before = sqlite3.connect("file:C:/Projects/personalfinanceapp/backend/finance.db.bak-2026-10-14-pre-dedupe?mode=ro", uri=True)
now = sqlite3.connect("file:C:/Projects/personalfinanceapp/backend/finance.db?mode=ro", uri=True)
acct_ids = dict(before.execute("select name, id from accounts"))
all_rows = {h: (i, a, date.fromisoformat(d), amt, desc) for i, a, d, amt, desc, h in
            before.execute("select id, account_id, date, amount_cents, description, source_row_hash from transactions")}
by_id = {v[0]: v for v in all_rows.values()}
kept_ids = {r[0] for r in now.execute("select id from transactions")}
deleted_ids = {v[0] for v in all_rows.values()} - kept_ids

files = sorted((p for p in DATA.glob("*.csv")), key=lambda p: p.stat().st_mtime)
file_rows = []  # (file, account_id, hash, parsed_row)
for f in files:
    try:
        entry = match(f.name); rows = get_parser(entry.parser).parse(f.read_bytes())
    except Exception as e:
        print(f"SKIP {f.name}: {e}"); file_rows.append((f, [])); continue
    by_acct = {}
    for r in rows:
        by_acct.setdefault(acct_ids[resolve_account_definition(entry, r.account_match_key).name], []).append(r)
    out = []
    for a, rs in by_acct.items():
        out += [(a, h, r) for h, r in zip(compute_row_hashes(a, rs), rs)]
    file_rows.append((f, out))

origin = {}
for idx, (f, rows) in enumerate(file_rows):
    for a, h, r in rows:
        origin.setdefault(h, idx)
unexplained = [v for h, v in all_rows.items() if h not in origin]
print(f"DB rows not traceable to any file in data/: {len(unexplained)}")

fp, tp = [], []
held_deleted = set()
for idx, (f, rows) in enumerate(file_rows):
    earlier = [(h, v) for h, v in all_rows.items() if origin.get(h, -1) < idx]
    claimed = {h for a, h, r in rows if h in all_rows and origin.get(h, -1) < idx}
    new_rows, parsed = [], []
    for a, h, r in rows:
        if h not in all_rows or h in claimed or origin.get(h) != idx:
            continue
        new_rows.append(NewRow(account_id=a, date=r.date, amount_cents=r.amount_cents, row_hash=h))
        parsed.append(r)
    existing_rows = [ExistingRow(id=eid, account_id=ea, date=ed, amount_cents=eamt)
                     for eh, (eid, ea, ed, eamt, edesc) in earlier if eh not in claimed]
    for i, existing_id in find_suspected_duplicates(new_rows, existing_rows, window_days=WINDOW).items():
        r = parsed[i]
        _, _, ed, _, edesc = by_id[existing_id]
        row_id = all_rows[new_rows[i].row_hash][0]
        item = (f.name, r.date, r.amount_cents / 100, r.description[:32], "<->", ed, edesc[:28])
        if row_id in deleted_ids:
            tp.append(item); held_deleted.add(row_id)
        else:
            fp.append(item)
missed = deleted_ids - held_deleted
print(f"\nwindow={WINDOW}d  true positives (deleted dups held): {len(tp)}  missed dups: {len(missed)}  false positives: {len(fp)}")
print("missed ids:", sorted(missed))
print("\nFALSE POSITIVES:")
for x in fp: print("  ", x)
