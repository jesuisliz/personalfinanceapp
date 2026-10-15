import pytest

from app.categories.candidate import normalize_rule_text, suggest_match_pattern


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("AplPay WALGREENS LAS VEGAS NV", "WALGREENS LAS VEGAS NV"),
        ("PRUDENTIAL DES:EDI PYMNTS ID:1", "PRUDENTIAL"),
        ("SQ *7-ELEVEN 1234", "SQ *7-ELEVEN"),
        ("PM *iDrama 555", "PM *iDrama"),
        ("TST* TATTE BAKERY BOSTON MA", "TST* TATTE"),
        ("IC* INSTACART SAN FRANCISCOCA", "IC* INSTACART"),
        ("UBER   *TRIP HELP.UBER.COM", "UBER   *TRIP"),
        ("VZWRLSS*APOCC VISN 04/21", "VZWRLSS*APOCC"),
        ("TRADER JOE S #519 PORTLAND ME", "TRADER JOE S"),
        (
            "Online scheduled transfer from CHK 1962 Confirmation# 1",
            "Online scheduled transfer from CHK",
        ),
        ("MACYS  ROCKINGHAM PK", "MACYS  ROCKINGHAM PK"),
        ("ONLINE STORE * 99", "ONLINE STORE *"),
        ("7-ELEVEN 33012 BOSTON", "7-ELEVEN 33012 BOSTON"),
        ("AplPay SQ", "AplPay SQ"),
        ("KFC J123 TOKYO", "KFC J123 TOKYO"),
        ("ACME*", "ACME*"),
    ],
)
def test_suggest_match_pattern(description, expected):
    result = suggest_match_pattern(description)

    assert result == expected
    assert result.lower() in description.lower()


def test_normalize_rule_text_strips_whitespace():
    assert normalize_rule_text("  KURA  ") == "KURA"


@pytest.mark.parametrize("value", ["", "   "])
def test_normalize_rule_text_rejects_blank(value):
    with pytest.raises(ValueError):
        normalize_rule_text(value)
