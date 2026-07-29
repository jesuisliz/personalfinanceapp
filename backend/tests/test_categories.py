from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.categories.apply import apply_category_rules, apply_merchant_rules
from app.categories.seed import SEED_TAXONOMY, seed_categories
from app.db import Base
from app.models import Account, Category, CategoryRule, MerchantRule, Transaction


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_account(session, name="Checking", institution="Bank of America"):
    account = Account(name=name, institution=institution, account_type="checking")
    session.add(account)
    session.commit()
    return account


_hash_counter = 0


def make_txn(session, account_id, raw_category, category_id=None):
    global _hash_counter
    _hash_counter += 1
    txn = Transaction(
        account_id=account_id,
        date=date(2026, 7, 1),
        description="txn",
        amount_cents=-1000,
        raw_category=raw_category,
        category_id=category_id,
        source_row_hash=f"hash-{_hash_counter}",
    )
    session.add(txn)
    session.commit()
    return txn


def test_seed_creates_all_categories_and_rules():
    session = make_session()
    seed_categories(session)

    categories = session.execute(select(Category)).scalars().all()
    assert len(categories) == len(SEED_TAXONOMY)

    total_rules = sum(len(mappings) for _, mappings in SEED_TAXONOMY)
    rules = session.execute(select(CategoryRule)).scalars().all()
    assert len(rules) == total_rules


def test_seed_is_idempotent():
    session = make_session()
    seed_categories(session)
    seed_categories(session)  # run twice

    categories = session.execute(select(Category)).scalars().all()
    assert len(categories) == len(SEED_TAXONOMY)


def test_chase_payment_maps_to_transfers_category():
    session = make_session()
    seed_categories(session)

    rule = session.execute(
        select(CategoryRule).where(
            CategoryRule.institution == "Chase", CategoryRule.raw_category == "Payment"
        )
    ).scalar_one()
    category = session.get(Category, rule.category_id)
    assert category.name == "Transfers"


def test_boa_restaurants_dining_maps_to_dining_and_drinks():
    session = make_session()
    seed_categories(session)

    rule = session.execute(
        select(CategoryRule).where(
            CategoryRule.institution == "Bank of America",
            CategoryRule.raw_category == "Restaurants/Dining",
        )
    ).scalar_one()
    category = session.get(Category, rule.category_id)
    assert category.name == "Dining & Drinks"


def test_account_specific_rule_overrides_institution_wide_rule():
    """One BofA account reuses the "Refunds/Adjustments" raw_category to mean something
    different than it does on every other BofA account (a card payment, not a refund) -
    an account-scoped rule must win over the institution-wide one for that account only."""
    session = make_session()
    fees = Category(name="Fees & Adjustments")
    payments = Category(name="Credit Card Payment")
    session.add_all([fees, payments])
    session.commit()

    special_account = make_account(session, name="Special Card")
    other_account = make_account(session, name="Regular Card")

    session.add_all(
        [
            CategoryRule(
                institution="Bank of America", raw_category="Refunds/Adjustments", category_id=fees.id
            ),
            CategoryRule(
                institution="Bank of America",
                raw_category="Refunds/Adjustments",
                category_id=payments.id,
                account_id=special_account.id,
            ),
        ]
    )
    session.commit()

    special_txn = make_txn(session, special_account.id, "Refunds/Adjustments")
    other_txn = make_txn(session, other_account.id, "Refunds/Adjustments")

    apply_category_rules(session)

    session.refresh(special_txn)
    session.refresh(other_txn)
    assert special_txn.category_id == payments.id
    assert other_txn.category_id == fees.id


def test_seed_is_safe_alongside_account_specific_rule():
    """Regression test: seed_categories used to look up an existing rule by
    (institution, raw_category) alone, which raised MultipleResultsFound once an
    account-specific override shared that pair with the institution-wide seeded rule."""
    session = make_session()
    seed_categories(session)

    fees_rule = session.execute(
        select(CategoryRule).where(
            CategoryRule.institution == "Bank of America",
            CategoryRule.raw_category == "Refunds/Adjustments",
        )
    ).scalar_one()
    payments = Category(name="Credit Card Payment")
    session.add(payments)
    session.commit()
    account = make_account(session, name="Special Card")
    session.add(
        CategoryRule(
            institution="Bank of America",
            raw_category="Refunds/Adjustments",
            category_id=payments.id,
            account_id=account.id,
        )
    )
    session.commit()

    seed_categories(session)  # must not raise MultipleResultsFound

    rules = session.execute(
        select(CategoryRule).where(
            CategoryRule.institution == "Bank of America",
            CategoryRule.raw_category == "Refunds/Adjustments",
        )
    ).scalars().all()
    assert len(rules) == 2
    assert {r.category_id for r in rules} == {fees_rule.category_id, payments.id}


def test_merchant_rule_wins_over_raw_category_when_applied_first():
    """A bank's native export can supply its own generic raw_category (e.g.
    "Other Expenses") for a transaction that a merchant rule also recognizes by
    name (e.g. a utility company). The merchant match is the more accurate
    signal, so the pipeline must run apply_merchant_rules before
    apply_category_rules - otherwise the generic raw_category rule claims the
    transaction first and the merchant rule's category never gets applied."""
    session = make_session()
    fees = Category(name="Fees & Adjustments")
    utilities = Category(name="Bills & Utilities")
    session.add_all([fees, utilities])
    session.commit()

    account = make_account(session)
    session.add(
        CategoryRule(institution="Bank of America", raw_category="Other Expenses", category_id=fees.id)
    )
    session.add(MerchantRule(match_pattern="cmp", clean_name="Central Maine Power", category_id=utilities.id))
    session.commit()

    txn = Transaction(
        account_id=account.id,
        date=date(2026, 5, 7),
        description="Cmp",
        amount_cents=-26259,
        raw_category="Other Expenses",
        source_row_hash="hash-cmp-precedence-test",
    )
    session.add(txn)
    session.commit()

    apply_merchant_rules(session)
    apply_category_rules(session)

    session.refresh(txn)
    assert txn.clean_description == "Central Maine Power"
    assert txn.category_id == utilities.id


def test_account_scoped_merchant_rule_overrides_global_rule_for_same_text():
    """Some bank statement text is generic enough (e.g. "PAYMENT - THANK YOU") to
    carry no identifying info about which specific card it belongs to. An
    account-scoped merchant rule must win over a global rule matching the same
    text for that one account, while other accounts still fall back to the
    global rule - otherwise a rule meant for one card would mislabel another
    card's payments that happen to use the same generic phrasing."""
    session = make_session()
    payments = Category(name="Credit Card Payment")
    session.add(payments)
    session.commit()

    cash_rewards = make_account(session, name="BOA Customized Cash Rewards")
    travel_rewards = make_account(session, name="BOA Travel Rewards Visa Signature")

    session.add_all(
        [
            MerchantRule(match_pattern="PAYMENT - THANK YOU", clean_name="Generic Card Payment", category_id=payments.id),
            MerchantRule(
                match_pattern="PAYMENT - THANK YOU",
                clean_name="BofA Cash Rewards Card Payment",
                category_id=payments.id,
                account_id=cash_rewards.id,
            ),
        ]
    )
    session.commit()

    cash_rewards_txn = Transaction(
        account_id=cash_rewards.id,
        date=date(2026, 1, 23),
        description="PAYMENT - THANK YOU",
        amount_cents=40028,
        source_row_hash="hash-cash-rewards-payment",
    )
    travel_rewards_txn = Transaction(
        account_id=travel_rewards.id,
        date=date(2026, 1, 23),
        description="PAYMENT - THANK YOU",
        amount_cents=20000,
        source_row_hash="hash-travel-rewards-payment",
    )
    session.add_all([cash_rewards_txn, travel_rewards_txn])
    session.commit()

    apply_merchant_rules(session)

    session.refresh(cash_rewards_txn)
    session.refresh(travel_rewards_txn)
    assert cash_rewards_txn.clean_description == "BofA Cash Rewards Card Payment"
    assert travel_rewards_txn.clean_description == "Generic Card Payment"
