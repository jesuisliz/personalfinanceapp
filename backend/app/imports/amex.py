import csv
import io
import re
from datetime import datetime

from app.imports.base import ParsedRow, parse_amount_to_cents


class AmexParser:
    def parse(self, file_bytes: bytes) -> list[ParsedRow]:
        text = file_bytes.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for line_num, raw in enumerate(reader, start=2):
            try:
                # Amex's own convention is inverted from every other source: positive = charge,
                # negative = payment/credit. Negate to match our negative = expense convention.
                amount_cents = -parse_amount_to_cents(raw["Amount"])
                rows.append(
                    ParsedRow(
                        date=datetime.strptime(raw["Date"].strip(), "%m/%d/%Y").date(),
                        posted_date=None,
                        description=re.sub(r"\s+", " ", raw["Description"]).strip(),
                        amount_cents=amount_cents,
                        raw_category=None,
                        memo=None,
                    )
                )
            except Exception as exc:
                raise ValueError(f"Amex parser failed on row {line_num}: {raw!r} ({exc})") from exc
        return rows
