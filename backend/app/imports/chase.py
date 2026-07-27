import csv
import html
import io
from datetime import datetime

from app.imports.base import ParsedRow, parse_amount_to_cents


class ChaseParser:
    def parse(self, file_bytes: bytes) -> list[ParsedRow]:
        text = file_bytes.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for line_num, raw in enumerate(reader, start=2):
            try:
                memo = (raw.get("Memo") or "").strip() or None
                raw_category = raw.get("Category") or None
                # Chase leaves Category blank on Payment-type rows (confirmed against
                # real data); synthesize a raw_category so these flow through the same
                # category-mapping mechanism as every other row instead of being
                # permanently uncategorized.
                if raw_category is None and raw.get("Type") == "Payment":
                    raw_category = "Payment"
                rows.append(
                    ParsedRow(
                        date=datetime.strptime(raw["Transaction Date"], "%m/%d/%Y").date(),
                        posted_date=datetime.strptime(raw["Post Date"], "%m/%d/%Y").date(),
                        description=html.unescape(raw["Description"]),
                        amount_cents=parse_amount_to_cents(raw["Amount"]),
                        raw_category=raw_category,
                        memo=memo,
                    )
                )
            except Exception as exc:
                raise ValueError(f"Chase parser failed on row {line_num}: {raw!r} ({exc})") from exc
        return rows
