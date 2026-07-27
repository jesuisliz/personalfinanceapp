import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

ACCOUNTS_CONFIG_PATH = Path(__file__).parent / "imports" / "accounts.yaml"


@dataclass
class RowFilter:
    account_name_contains: str


@dataclass
class AccountDefinition:
    name: str
    institution: str
    account_type: str
    row_filter: RowFilter | None = None


@dataclass
class ConfigEntry:
    match: str
    parser: str
    accounts: list[AccountDefinition] = field(default_factory=list)


def load_accounts_config(path: Path = ACCOUNTS_CONFIG_PATH) -> list[ConfigEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = []
    for item in raw:
        accounts = []
        for acct in item["accounts"]:
            row_filter = None
            if "row_filter" in acct:
                row_filter = RowFilter(account_name_contains=acct["row_filter"]["account_name_contains"])
            accounts.append(
                AccountDefinition(
                    name=acct["name"],
                    institution=acct["institution"],
                    account_type=acct["account_type"],
                    row_filter=row_filter,
                )
            )
        entries.append(ConfigEntry(match=item["match"], parser=item["parser"], accounts=accounts))
    return entries
