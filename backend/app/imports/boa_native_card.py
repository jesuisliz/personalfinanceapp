import csv
import io
import re
from datetime import datetime

from app.imports.base import ParsedRow, parse_amount_to_cents


class BoaNativeCardParser:
    """Parses BofA's native credit card CSV export (per-account download,
    not the aggregator export `BoaParser` handles). Only a single
    Posted Date column is given, so unlike the aggregator export there is
    no pending/posted distinction to preserve."""

    def parse(self, file_bytes: bytes) -> list[ParsedRow]:
        text = file_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for line_num, raw in enumerate(reader, start=2):
            try:
                rows.append(
                    ParsedRow(
                        date=datetime.strptime(raw["Posted Date"].strip(), "%m/%d/%Y").date(),
                        posted_date=None,
                        description=re.sub(r"\s+", " ", raw["Payee"]).strip(),
                        amount_cents=parse_amount_to_cents(raw["Amount"]),
                        raw_category=None,
                        memo=None,
                    )
                )
            except Exception as exc:
                raise ValueError(f"BOA native card parser failed on row {line_num}: {raw!r} ({exc})") from exc
        return rows
