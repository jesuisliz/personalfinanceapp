import csv
import io
import re
from datetime import datetime

from app.imports.base import ParsedRow, parse_amount_to_cents


class UsBankParser:
    def parse(self, file_bytes: bytes) -> list[ParsedRow]:
        text = file_bytes.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for line_num, raw in enumerate(reader, start=2):
            try:
                txn_type = raw["Transaction"].strip().upper()
                magnitude = parse_amount_to_cents(raw["Amount"])
                if txn_type == "CREDIT":
                    amount_cents = magnitude
                elif txn_type == "DEBIT":
                    amount_cents = -magnitude
                else:
                    raise ValueError(f"Unrecognized US Bank Transaction type: {raw['Transaction']!r}")

                memo = (raw.get("Memo") or "").strip() or None
                rows.append(
                    ParsedRow(
                        date=datetime.strptime(raw["Date"].strip(), "%Y-%m-%d").date(),
                        posted_date=None,
                        description=re.sub(r"\s+", " ", raw["Name"]).strip(),
                        amount_cents=amount_cents,
                        raw_category=None,
                        memo=memo,
                    )
                )
            except Exception as exc:
                raise ValueError(f"US Bank parser failed on row {line_num}: {raw!r} ({exc})") from exc
        return rows
