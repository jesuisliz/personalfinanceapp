import csv
import io
from datetime import datetime

from app.imports.base import ParsedRow, parse_amount_to_cents


class BoaParser:
    def parse(self, file_bytes: bytes) -> list[ParsedRow]:
        text = file_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for line_num, raw in enumerate(reader, start=2):
            try:
                txn_date = datetime.strptime(raw["Date"].strip(), "%m/%d/%Y").date()
                posted_date = None if raw["Status"].strip().lower() == "pending" else txn_date
                memo = (raw.get("Memo") or "").strip() or None
                rows.append(
                    ParsedRow(
                        date=txn_date,
                        posted_date=posted_date,
                        description=raw["Simple Description"].strip(),
                        amount_cents=parse_amount_to_cents(raw["Amount"]),
                        raw_category=raw.get("Category") or None,
                        memo=memo,
                        account_match_key=raw["Account Name"].strip(),
                    )
                )
            except Exception as exc:
                raise ValueError(f"BOA parser failed on row {line_num}: {raw!r} ({exc})") from exc
        return rows
