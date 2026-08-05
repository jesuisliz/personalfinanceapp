from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Transaction
from app.schemas import CategoryBreakdownOut, MerchantBreakdownOut, MonthlySummaryOut, SavingsEstimateOut

UNCATEGORIZED_LABEL = "Uncategorized"
# Categories that represent internal money movement rather than real income or
# spending: transfers between the user's own accounts, and credit card payments
# (paying off a card isn't spending - the spending was already counted when the
# purchases happened).
NON_SPENDING_CATEGORY_NAMES = ("Transfers", "Credit Card Payment")


def _load_real_transactions(session: Session, account_id: int | None) -> list[Transaction]:
    """All transactions excluding internal money movement: confirmed is_transfer pairs,
    and anything categorized as one of NON_SPENDING_CATEGORY_NAMES even if it hasn't been
    matched to a counterpart yet (an ATM withdrawal or CC payment is internal money
    movement, not spending or income, whether or not its confirmed pair has been found)."""
    non_spending_category_ids = {
        c.id
        for c in session.execute(
            select(Category).where(Category.name.in_(NON_SPENDING_CATEGORY_NAMES))
        ).scalars().all()
    }

    stmt = select(Transaction)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    transactions = session.execute(stmt).scalars().all()

    return [t for t in transactions if not t.is_transfer and t.category_id not in non_spending_category_ids]


def latest_transaction_date(session: Session, account_id: int | None) -> date | None:
    stmt = select(Transaction)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    transactions = session.execute(stmt).scalars().all()
    if not transactions:
        return None
    return max(t.date for t in transactions)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _trailing_month_keys(latest: date, months: int) -> list[str]:
    """Oldest-to-newest list of `months` calendar-month keys ending at `latest`'s month."""
    keys = []
    year, month = latest.year, latest.month
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(keys))


def monthly_summary(session: Session, months: int, account_id: int | None) -> list[MonthlySummaryOut]:
    latest = latest_transaction_date(session, account_id)
    if latest is None:
        return []

    month_keys = _trailing_month_keys(latest, months)
    month_key_set = set(month_keys)
    income: dict[str, int] = defaultdict(int)
    expense: dict[str, int] = defaultdict(int)

    for t in _load_real_transactions(session, account_id):
        key = _month_key(t.date)
        if key not in month_key_set:
            continue
        if t.amount_cents >= 0:
            income[key] += t.amount_cents
        else:
            expense[key] += -t.amount_cents

    return [
        MonthlySummaryOut(
            month=key,
            income_cents=income[key],
            expense_cents=expense[key],
            net_cents=income[key] - expense[key],
        )
        for key in month_keys
    ]


def category_breakdown(session: Session, month: str | None, account_id: int | None) -> list[CategoryBreakdownOut]:
    """`month=None` returns an all-time breakdown across every transaction, not just
    one month - used by the Dashboard's "All months" option."""
    category_names = {c.id: c.name for c in session.execute(select(Category)).scalars().all()}
    totals: dict[int | None, int] = defaultdict(int)

    for t in _load_real_transactions(session, account_id):
        if t.amount_cents >= 0 or (month is not None and _month_key(t.date) != month):
            continue
        totals[t.category_id] += -t.amount_cents

    rows = [
        CategoryBreakdownOut(
            category_id=category_id,
            category_name=category_names.get(category_id, UNCATEGORIZED_LABEL),
            total_cents=total,
        )
        for category_id, total in totals.items()
    ]
    rows.sort(key=lambda r: r.total_cents, reverse=True)
    return rows


def income_breakdown(session: Session, month: str | None, account_id: int | None) -> list[CategoryBreakdownOut]:
    """`month=None` returns an all-time breakdown across every transaction, not just
    one month - used by the Dashboard's "All months" option. Mirrors category_breakdown
    but for the income side: every positive-amount transaction, grouped by whatever
    category it's actually in. This deliberately includes refunds that land back in an
    ordinary spending category (e.g. a "Shopping" refund) rather than hiding or
    reclassifying them - it shows what's really there instead of guessing at intent."""
    category_names = {c.id: c.name for c in session.execute(select(Category)).scalars().all()}
    totals: dict[int | None, int] = defaultdict(int)

    for t in _load_real_transactions(session, account_id):
        if t.amount_cents <= 0 or (month is not None and _month_key(t.date) != month):
            continue
        totals[t.category_id] += t.amount_cents

    rows = [
        CategoryBreakdownOut(
            category_id=category_id,
            category_name=category_names.get(category_id, UNCATEGORIZED_LABEL),
            total_cents=total,
        )
        for category_id, total in totals.items()
    ]
    rows.sort(key=lambda r: r.total_cents, reverse=True)
    return rows


def income_transactions(
    session: Session, month: str | None, account_id: int | None, category_id: int | None, uncategorized: bool
) -> list[Transaction]:
    """The exact set of income transactions that fed one category's total in
    income_breakdown, for drill-down display. Mirrors category_transactions but for the
    income side. `month=None` returns every matching transaction across all time in a
    single call, rather than requiring one call per month."""
    matches = []
    for t in _load_real_transactions(session, account_id):
        if t.amount_cents <= 0 or (month is not None and _month_key(t.date) != month):
            continue
        if uncategorized:
            if t.category_id is not None:
                continue
        elif t.category_id != category_id:
            continue
        matches.append(t)

    matches.sort(key=lambda t: t.date, reverse=True)
    return matches


def non_spending_category_transactions(
    session: Session, month: str | None, account_id: int | None, category_id: int
) -> list[Transaction]:
    """The transactions in a NON_SPENDING_CATEGORY_NAMES category (Transfers, Credit
    Card Payment), shown directly. These categories are excluded from
    `category_breakdown` entirely (see `_load_real_transactions`), so they have no
    spending total to drill into - unlike `category_transactions`, this includes
    both directions of money movement, not just the expense side. `month=None`
    returns every transaction in the category across all time in a single call,
    rather than requiring one call per month."""
    stmt = select(Transaction).where(Transaction.category_id == category_id)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    transactions = session.execute(stmt).scalars().all()

    matches = [t for t in transactions if month is None or _month_key(t.date) == month]
    matches.sort(key=lambda t: t.date, reverse=True)
    return matches


def category_transactions(
    session: Session, month: str | None, account_id: int | None, category_id: int | None, uncategorized: bool
) -> list[Transaction]:
    """The exact set of expense transactions that fed one category's total in
    `category_breakdown`, for drill-down display. Same filters, same month scope,
    just narrowed to one category instead of grouped across all of them. `month=None`
    returns every matching transaction across all time in a single call, rather than
    requiring one call per month."""
    matches = []
    for t in _load_real_transactions(session, account_id):
        if t.amount_cents >= 0 or (month is not None and _month_key(t.date) != month):
            continue
        if uncategorized:
            if t.category_id is not None:
                continue
        elif t.category_id != category_id:
            continue
        matches.append(t)

    matches.sort(key=lambda t: t.date, reverse=True)
    return matches


def category_trends(
    session: Session, months: int, account_id: int | None
) -> dict[str, list[CategoryBreakdownOut]]:
    """Full category breakdown for each of the trailing `months` months — lets a caller
    (e.g. the chatbot) see which categories rose or fell without the caller doing any
    summing itself; every number here already comes straight from `category_breakdown`."""
    latest = latest_transaction_date(session, account_id)
    if latest is None:
        return {}

    month_keys = _trailing_month_keys(latest, months)
    return {month: category_breakdown(session, month, account_id) for month in month_keys}


def estimate_category_reduction_savings(
    session: Session,
    category_id: int | None,
    uncategorized: bool,
    reduction_percent: float,
    months: int,
    account_id: int | None,
) -> SavingsEstimateOut:
    """Backend-computed answer to "how much could I save by reducing X by Y%": average
    that category's actual spend over the trailing `months` (zero-filling months with no
    spend, same convention as `monthly_summary`), then apply the reduction. The caller
    (the chatbot) never does this arithmetic itself."""
    latest = latest_transaction_date(session, account_id)
    if latest is None:
        return SavingsEstimateOut(
            avg_monthly_cents=0, monthly_savings_cents=0, annual_savings_cents=0, months_considered=0
        )

    month_keys = _trailing_month_keys(latest, months)
    total_cents = 0
    for month in month_keys:
        for row in category_breakdown(session, month, account_id):
            matches = row.category_id is None if uncategorized else row.category_id == category_id
            if matches:
                total_cents += row.total_cents
                break

    avg_monthly_cents = total_cents // len(month_keys)
    monthly_savings_cents = round(avg_monthly_cents * reduction_percent / 100)

    return SavingsEstimateOut(
        avg_monthly_cents=avg_monthly_cents,
        monthly_savings_cents=monthly_savings_cents,
        annual_savings_cents=monthly_savings_cents * 12,
        months_considered=len(month_keys),
    )


def merchant_transactions(
    session: Session, merchant_search: str, months: int | None, account_id: int | None
) -> list[Transaction]:
    """Every transaction whose description mentions `merchant_search` (case-insensitive
    substring against clean_description falling back to description, the same matching
    rule the Transactions page's own Merchant filter already uses), optionally restricted
    to the trailing `months` months. `months=None` searches all time. Unlike
    category_transactions, this does not filter through _load_real_transactions - a
    merchant/payee search is about a real-world counterparty, and should include the
    money whether or not it happens to be flagged as an internal transfer."""
    search_lower = merchant_search.lower()

    month_key_set = None
    if months is not None:
        latest = latest_transaction_date(session, account_id)
        if latest is None:
            return []
        month_key_set = set(_trailing_month_keys(latest, months))

    stmt = select(Transaction)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    transactions = session.execute(stmt).scalars().all()

    matches = [
        t
        for t in transactions
        if search_lower in (t.clean_description or t.description).lower()
        and (month_key_set is None or _month_key(t.date) in month_key_set)
    ]
    matches.sort(key=lambda t: t.date, reverse=True)
    return matches


def top_merchants(session: Session, month: str | None, account_id: int | None, limit: int) -> list[MerchantBreakdownOut]:
    """`month=None` returns all-time top merchants - used by the Dashboard's "All
    months" option."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)

    for t in _load_real_transactions(session, account_id):
        if t.amount_cents >= 0 or (month is not None and _month_key(t.date) != month):
            continue
        merchant = t.clean_description or t.description
        totals[merchant] += -t.amount_cents
        counts[merchant] += 1

    rows = [
        MerchantBreakdownOut(merchant=merchant, total_cents=total, transaction_count=counts[merchant])
        for merchant, total in totals.items()
    ]
    rows.sort(key=lambda r: r.total_cents, reverse=True)
    return rows[:limit]
