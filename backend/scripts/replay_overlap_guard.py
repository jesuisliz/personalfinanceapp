"""Measure the proposed overlap-guard rule against real import history (read-only).

Origin of each DB row = the earliest file (by mtime) whose parsed rows hash to it.
For each file in mtime order, rows not already present from an earlier file are candidates;
they are paired (same account, same amount, |date diff| <= WINDOW, one-to-one, closest first)
against rows that came from earlier files. See docs/lld_import_overlap_guard_claude.md.

Phase 1 of that LLD replaces the inline pairing below with the real pairing function.
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

WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 3
DATA = Path("C:/Projects/personalfinanceapp/data")
before = sqlite3.connect("file:C:/Projects/personalfinanceapp/backend/finance.db.bak-2026-10-14-pre-dedupe?mode=ro", uri=True)
now = sqlite3.connect("file:C:/Projects/personalfinanceapp/backend/finance.db?mode=ro", uri=True)
acct_ids = dict(before.execute("select name, id from accounts"))
all_rows = {h: (i, a, date.fromisoformat(d), amt, desc) for i, a, d, amt, desc, h in
            before.execute("select id, account_id, date, amount_cents, description, source_row_hash from transactions")}
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
    cands = []
    for pos, (a, h, r) in enumerate(rows):
        if h not in all_rows or h in claimed or origin.get(h) != idx:
            continue
        for eh, (eid, ea, ed, eamt, edesc) in earlier:
            if eh in claimed or ea != a or eamt != r.amount_cents:
                continue
            diff = abs((ed - r.date).days)
            if diff <= WINDOW:
                cands.append((diff, eid, pos, h, r, eh, edesc, ed))
    taken_new = set()
    for diff, eid, pos, h, r, eh, edesc, ed in sorted(cands, key=lambda c: c[:3]):
        if pos in taken_new or eh in claimed:
            continue
        taken_new.add(pos); claimed.add(eh)
        row_id = all_rows[h][0]
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
