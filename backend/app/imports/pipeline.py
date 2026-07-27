from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.categories.apply import apply_category_rules, apply_merchant_rules
from app.config import AccountDefinition, ConfigEntry
from app.imports.base import ParsedRow, compute_row_hashes
from app.imports.registry import get_parser, match
from app.models import Account, Transaction


@dataclass
class ImportSummary:
    filename: str
    rows_seen: int
    rows_inserted: int
    rows_skipped_as_duplicate: int


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


def import_file(session: Session, filename: str, file_bytes: bytes) -> ImportSummary:
    config_entry = match(filename)
    parser = get_parser(config_entry.parser)
    rows = parser.parse(file_bytes)

    rows_by_account_id: dict[int, list[ParsedRow]] = {}
    for row in rows:
        account_def = resolve_account_definition(config_entry, row.account_match_key)
        account = get_or_create_account(session, account_def)
        rows_by_account_id.setdefault(account.id, []).append(row)

    rows_inserted = 0
    for account_id, account_rows in rows_by_account_id.items():
        row_hashes = compute_row_hashes(account_id, account_rows)
        for row, row_hash in zip(account_rows, row_hashes):
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
            result = session.execute(stmt)
            rows_inserted += result.rowcount

    session.commit()
    apply_category_rules(session)
    apply_merchant_rules(session)

    return ImportSummary(
        filename=filename,
        rows_seen=len(rows),
        rows_inserted=rows_inserted,
        rows_skipped_as_duplicate=len(rows) - rows_inserted,
    )
