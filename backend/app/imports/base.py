import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass
class ParsedRow:
    date: date
    posted_date: date | None
    description: str
    amount_cents: int
    raw_category: str | None
    memo: str | None
    account_match_key: str | None = None


class Parser(Protocol):
    def parse(self, file_bytes: bytes) -> list[ParsedRow]: ...


def parse_amount_to_cents(raw: str) -> int:
    cleaned = raw.replace(",", "").strip()
    return int(Decimal(cleaned) * 100)


def compute_row_hashes(account_id: int, rows: list[ParsedRow]) -> list[str]:
    """Hash rows for dedupe, in file order.

    Includes each row's occurrence index within this account's rows so that
    genuinely repeated transactions (same date/amount/description, e.g. two
    people using a shared card for the same purchase) are not collapsed into
    one — while re-importing the same file still reproduces identical hashes
    and is correctly treated as a no-op.
    """
    seen_counts: dict[str, int] = {}
    hashes = []
    for row in rows:
        base_key = f"{account_id}|{row.date.isoformat()}|{row.amount_cents}|{row.description.strip().lower()}"
        occurrence = seen_counts.get(base_key, 0)
        seen_counts[base_key] = occurrence + 1
        key = f"{base_key}|{occurrence}"
        hashes.append(hashlib.sha256(key.encode("utf-8")).hexdigest())
    return hashes
