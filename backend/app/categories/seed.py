from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, CategoryRule

# (category_name, [(institution, raw_category), ...])
# Grounded in the actual raw categories observed across all real files in data/ —
# see docs/lld_phase2_claude.md Section 1 for the frequency counts this was derived from.
SEED_TAXONOMY: list[tuple[str, list[tuple[str, str]]]] = [
    ("Dining & Drinks", [("Chase", "Food & Drink"), ("Bank of America", "Restaurants/Dining")]),
    ("Groceries", [("Chase", "Groceries"), ("Bank of America", "Groceries")]),
    (
        "Shopping",
        [
            ("Chase", "Shopping"),
            ("Bank of America", "General Merchandise"),
            ("Bank of America", "Clothing/Shoes"),
            ("Bank of America", "Electronics"),
            ("Bank of America", "Hobbies"),
        ],
    ),
    ("Travel", [("Chase", "Travel"), ("Bank of America", "Travel")]),
    ("Automotive & Gas", [("Chase", "Automotive"), ("Chase", "Gas")]),
    ("Home", [("Chase", "Home"), ("Bank of America", "Home Improvement")]),
    (
        "Bills & Utilities",
        [
            ("Chase", "Bills & Utilities"),
            ("Bank of America", "Utilities"),
            ("Bank of America", "Telephone Services"),
            ("Bank of America", "Online Services"),
        ],
    ),
    ("Entertainment", [("Chase", "Entertainment"), ("Bank of America", "Entertainment")]),
    ("Health", [("Chase", "Health & Wellness"), ("Bank of America", "Healthcare/Medical")]),
    ("Personal Care", [("Bank of America", "Personal Care")]),
    ("Education", [("Chase", "Education")]),
    ("Child/Dependent", [("Bank of America", "Child/Dependent Expenses")]),
    (
        "Fees & Adjustments",
        [
            ("Chase", "Fees & Adjustments"),
            ("Bank of America", "Refunds/Adjustments"),
            ("Bank of America", "Other Expenses"),
        ],
    ),
    ("Income", [("Bank of America", "Paychecks/Salary")]),
    (
        "Interest & Investments",
        [
            ("Bank of America", "Interest"),
            ("Bank of America", "Securities Trades"),
            ("Bank of America", "Rewards"),
        ],
    ),
    (
        "Transfers",
        [
            ("Bank of America", "Transfers"),
            ("Bank of America", "Savings"),
            ("Bank of America", "Credit Card Payments"),
            ("Bank of America", "Loans"),
            ("Bank of America", "Checks"),
            ("Bank of America", "ATM/Cash Withdrawals"),
            ("Chase", "Payment"),
        ],
    ),
]


def seed_categories(session: Session) -> None:
    """Idempotent: safe to call on every startup. Only inserts what's missing."""
    for category_name, mappings in SEED_TAXONOMY:
        category = session.execute(
            select(Category).where(Category.name == category_name)
        ).scalar_one_or_none()
        if category is None:
            category = Category(name=category_name)
            session.add(category)
            session.flush()

        for institution, raw_category in mappings:
            # Seeding only ever manages institution-wide rules (account_id IS NULL) -
            # an account-specific override for the same (institution, raw_category)
            # is a separate row and must not be mistaken for this one, or vice versa.
            existing_rule = session.execute(
                select(CategoryRule).where(
                    CategoryRule.institution == institution,
                    CategoryRule.raw_category == raw_category,
                    CategoryRule.account_id.is_(None),
                )
            ).scalar_one_or_none()
            if existing_rule is None:
                session.add(
                    CategoryRule(
                        institution=institution,
                        raw_category=raw_category,
                        category_id=category.id,
                    )
                )

    session.commit()
