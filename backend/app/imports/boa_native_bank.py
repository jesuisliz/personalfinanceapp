import csv
import io
from datetime import datetime

from app.imports.base import ParsedRow, parse_amount_to_cents


class BoaNativeBankParser:
    """Parses BofA's native checking/savings CSV export (per-account download,
    not the aggregator export `BoaParser` handles). Has a 5-line summary
    block before the real header, and no Account Name column since each
    file is already scoped to one account."""

    def parse(self, file_bytes: bytes) -> list[ParsedRow]:
        text = file_bytes.decode("utf-8-sig")
        lines = text.splitlines()
        header_idx = next(i for i, line in enumerate(lines) if line.startswith("Date,"))
        reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
        rows = []
        for line_num, raw in enumerate(reader, start=header_idx + 2):
            amount_raw = (raw.get("Amount") or "").strip()
            if not amount_raw:
                continue  # "Beginning balance" row has no Amount, just a Running Bal.
            try:
                rows.append(
                    ParsedRow(
                        date=datetime.strptime(raw["Date"].strip(), "%m/%d/%Y").date(),
                        posted_date=None,
                        description=raw["Description"].strip(),
                        amount_cents=parse_amount_to_cents(amount_raw),
                        raw_category=None,
                        memo=None,
                    )
                )
            except Exception as exc:
                raise ValueError(f"BOA native bank parser failed on row {line_num}: {raw!r} ({exc})") from exc
        return rows
