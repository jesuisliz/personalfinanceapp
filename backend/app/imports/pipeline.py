from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.categories.apply import apply_all_rules
from app.config import AccountDefinition, ConfigEntry
from app.imports.base import ParsedRow, compute_row_hashes
from app.imports.overlap import WINDOW_DAYS, ExistingRow, NewRow, find_suspected_duplicates
from app.imports.registry import get_parser, match
from app.models import Account, Transaction


@dataclass
class SuspectedDuplicate:
    row_hash: str
    account_name: str
    date: date
    description: str
    amount_cents: int
    existing_id: int
    existing_date: date
    existing_description: str


@dataclass
class ImportSummary:
    filename: str
    rows_seen: int
    rows_inserted: int
    rows_skipped_as_duplicate: int
    rows_held_as_suspected_duplicate: int
    suspected_duplicates: list[SuspectedDuplicate]


def resolve_account_definition(
    config_entry: ConfigEntry, account_match_key: str | None
) -> AccountDefinition:
    if len(config_entry.accounts) == 1 and config_entry.accounts[0].row_filter is None:
        return config_entry.accounts[0]

    if account_match_key is None:
        raise ValueError(
            f"Config for '{config_entry.match}' defines multiple accounts but the parser "
            "did not provide an account_match_key for this row."
        )

    for account_def in config_entry.accounts:
        if account_def.row_filter and account_def.row_filter.account_name_contains in account_match_key:
            return account_def

    raise ValueError(
        f"No account in config for '{config_entry.match}' matches row account name: {account_match_key!r}"
    )


def get_or_create_account(session: Session, account_def: AccountDefinition) -> Account:
    existing = session.execute(
        select(Account).where(Account.name == account_def.name)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    account = Account(
        name=account_def.name,
        institution=account_def.institution,
        account_type=account_def.account_type,
    )
    session.add(account)
    session.flush()  # populate account.id without committing
    return account


def load_nearby_transactions(session: Session, account_id: int, rows: list[ParsedRow]) -> list[Transaction]:
    """Existing rows of one account dated within WINDOW_DAYS of that account's rows in the file.

    Includes every exact re-import too: a matching hash means the same account and date.
    """
    dates = [row.date for row in rows]
    start = min(dates) - timedelta(days=WINDOW_DAYS)
    end = max(dates) + timedelta(days=WINDOW_DAYS)
    return list(
        session.execute(
            select(Transaction).where(Transaction.account_id == account_id, Transaction.date.between(start, end))
        ).scalars()
    )


def find_partners(
    account_id: int, rows: list[ParsedRow], row_hashes: list[str], nearby: list[Transaction]
) -> dict[int, Transaction]:
    """Map row index -> the existing transaction it likely duplicates.

    Rows whose hash already exists are left out and take their own existing row out of the pool.
    """
    existing_hashes = {t.source_row_hash for t in nearby}
    file_hashes = set(row_hashes)
    pool = [t for t in nearby if t.source_row_hash not in file_hashes]
    candidate_indices = [i for i, row_hash in enumerate(row_hashes) if row_hash not in existing_hashes]
    new_rows = [
        NewRow(account_id, rows[i].date, rows[i].amount_cents, row_hashes[i]) for i in candidate_indices
    ]
    existing_rows = [ExistingRow(t.id, t.account_id, t.date, t.amount_cents) for t in pool]
    pool_by_id = {t.id: t for t in pool}
    pairs = find_suspected_duplicates(new_rows, existing_rows)
    return {candidate_indices[new_index]: pool_by_id[existing_id] for new_index, existing_id in pairs.items()}


def insert_row(session: Session, account_id: int, row: ParsedRow, row_hash: str) -> int:
    """Insert one parsed row; return 1 if inserted, 0 if its hash already existed."""
    stmt = (
        sqlite_insert(Transaction)
        .values(
            account_id=account_id,
            date=row.date,
            posted_date=row.posted_date,
            description=row.description,
            amount_cents=row.amount_cents,
            raw_category=row.raw_category,
            memo=row.memo,
            source_row_hash=row_hash,
        )
        .on_conflict_do_nothing(index_elements=["account_id", "source_row_hash"])
    )
    return session.execute(stmt).rowcount


def import_file(
    session: Session, filename: str, file_bytes: bytes, accept_hashes: frozenset[str] = frozenset()
) -> ImportSummary:
    """Import one CSV, holding rows that look like cross-format duplicates of existing rows.

    A held row is inserted on a later call whose accept_hashes contains its hash.
    See docs/lld_import_overlap_guard_claude.md.
    """
    config_entry = match(filename)
    parser = get_parser(config_entry.parser)
    rows = parser.parse(file_bytes)

    accounts_by_id: dict[int, Account] = {}
    rows_by_account_id: dict[int, list[ParsedRow]] = {}
    for row in rows:
        account_def = resolve_account_definition(config_entry, row.account_match_key)
        account = get_or_create_account(session, account_def)
        accounts_by_id[account.id] = account
        rows_by_account_id.setdefault(account.id, []).append(row)

    rows_inserted = 0
    rows_skipped = 0
    suspects: list[SuspectedDuplicate] = []
    for account_id, account_rows in rows_by_account_id.items():
        row_hashes = compute_row_hashes(account_id, account_rows)
        nearby = load_nearby_transactions(session, account_id, account_rows)
        existing_hashes = {t.source_row_hash for t in nearby}
        partners = find_partners(account_id, account_rows, row_hashes, nearby)
        for index, (row, row_hash) in enumerate(zip(account_rows, row_hashes)):
            if row_hash in existing_hashes:
                rows_skipped += 1
                continue
            partner = partners.get(index)
            if partner is not None and row_hash not in accept_hashes:
                suspects.append(
                    SuspectedDuplicate(
                        row_hash=row_hash,
                        account_name=accounts_by_id[account_id].name,
                        date=row.date,
                        description=row.description,
                        amount_cents=row.amount_cents,
                        existing_id=partner.id,
                        existing_date=partner.date,
                        existing_description=partner.description,
                    )
                )
                continue
            inserted = insert_row(session, account_id, row, row_hash)
            rows_inserted += inserted
            rows_skipped += 1 - inserted  # a concurrent import inserted the same hash first

    session.commit()
    apply_all_rules(session)

    suspects.sort(key=lambda s: (s.account_name, s.date, s.description, s.amount_cents, s.row_hash))
    return ImportSummary(
        filename=filename,
        rows_seen=len(rows),
        rows_inserted=rows_inserted,
        rows_skipped_as_duplicate=rows_skipped,
        rows_held_as_suspected_duplicate=len(suspects),
        suspected_duplicates=suspects,
    )
