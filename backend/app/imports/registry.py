from app.config import ConfigEntry, load_accounts_config
from app.imports.amex import AmexParser
from app.imports.base import Parser
from app.imports.boa import BoaParser
from app.imports.chase import ChaseParser
from app.imports.us_bank import UsBankParser

PARSERS: dict[str, Parser] = {
    "chase": ChaseParser(),
    "boa": BoaParser(),
    "us_bank": UsBankParser(),
    "amex": AmexParser(),
}


def match(filename: str, config_entries: list[ConfigEntry] | None = None) -> ConfigEntry:
    entries = config_entries if config_entries is not None else load_accounts_config()
    for entry in entries:
        if entry.match in filename:
            return entry
    raise ValueError(f"No account config matches filename: {filename!r}")


def get_parser(parser_name: str) -> Parser:
    try:
        return PARSERS[parser_name]
    except KeyError:
        raise ValueError(f"Unknown parser name in config: {parser_name!r}")
