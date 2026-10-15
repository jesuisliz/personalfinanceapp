"""Support for turning a manual category edit into a MerchantRule.

See docs/lld_edit_creates_merchant_rule_claude.md section 4.
"""

import re

APPLE_PAY_PREFIX = "AplPay "
MIN_PATTERN_LENGTH = 4


def normalize_rule_text(value: str) -> str:
    """Strip surrounding whitespace; reject a value that is blank afterwards.

    Used for both preview and create, so the pattern previewed is exactly the
    pattern stored.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def suggest_match_pattern(description: str) -> str:
    """Suggest a match_pattern for a rule built from `description`.

    A pre-fill only: the user sees and can edit it. The result is always a
    contiguous slice of `description`, so it always matches its own row.
    Algorithm (LLD 4.1): drop a leading "AplPay "; cut at " DES:"; else keep a
    single-token processor prefix plus the first word after its "*"; else keep
    the words before the first one containing a digit or "#". A result shorter
    than 4 characters falls back to the whole description.
    """
    start = len(APPLE_PAY_PREFIX) if description.startswith(APPLE_PAY_PREFIX) else 0
    body = description[start:]
    end = start + _suggested_body_end(body)
    pattern = description[start:end]
    if len(pattern) < MIN_PATTERN_LENGTH:
        return description
    return pattern


def _suggested_body_end(body: str) -> int:
    """Return the index in `body` where the suggested pattern ends."""
    des_index = body.find(" DES:")
    if des_index != -1:
        return des_index

    star = body.find("*")
    if star != -1 and _is_single_token(body[:star]):
        word_after_star = re.match(r"\s*\S+", body[star + 1:])
        if word_after_star is None:
            return star + 1
        return star + 1 + word_after_star.end()

    end = 0
    for token in re.finditer(r"\S+", body):
        if re.search(r"[\d#]", token.group()):
            break
        end = token.end()
    return end


def _is_single_token(text: str) -> bool:
    """True if `text`, stripped, is non-empty and has no internal whitespace."""
    stripped = text.strip()
    return bool(stripped) and not re.search(r"\s", stripped)
