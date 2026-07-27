from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.categories.apply import apply_merchant_rules
from app.db import Base
from app.models import Account, Category, MerchantRule, Transaction


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_transaction(session, description, account_id=1):
    txn = Transaction(
        account_id=account_id,
        date=date(2026, 1, 1),
        description=description,
        amount_cents=-1000,
        source_row_hash=f"hash-{description}",
    )
    session.add(txn)
    session.commit()
    return txn


def setup_account(session):
    account = Account(name="Test Account", institution="Chase", account_type="credit_card")
    session.add(account)
    session.commit()
    return account


def test_merchant_rule_sets_clean_description_case_insensitively():
    session = make_session()
    setup_account(session)
    session.add(MerchantRule(match_pattern="amazon mktpl", clean_name="Amazon"))
    session.commit()
    txn = make_transaction(session, "AMAZON MKTPL*MV7TW4A33")

    updated = apply_merchant_rules(session)

    assert updated == 1
    session.refresh(txn)
    assert txn.clean_description == "Amazon"


def test_merchant_rule_does_not_overwrite_manual_edit():
    session = make_session()
    setup_account(session)
    session.add(MerchantRule(match_pattern="amazon", clean_name="Amazon"))
    session.commit()
    txn = make_transaction(session, "AMAZON MKTPL*XYZ")
    txn.clean_description = "My Custom Name"
    session.commit()

    apply_merchant_rules(session)

    session.refresh(txn)
    assert txn.clean_description == "My Custom Name"


def test_merchant_rule_sets_category_only_if_transaction_has_none():
    session = make_session()
    setup_account(session)
    category = Category(name="Groceries")
    other_category = Category(name="Shopping")
    session.add_all([category, other_category])
    session.commit()
    session.add(MerchantRule(match_pattern="costco", clean_name="Costco", category_id=category.id))
    session.commit()

    already_categorized = make_transaction(session, "IC* COSTCO BY IN CAR")
    already_categorized.category_id = other_category.id
    session.commit()

    apply_merchant_rules(session)

    session.refresh(already_categorized)
    assert already_categorized.clean_description == "Costco"
    assert already_categorized.category_id == other_category.id  # untouched


def test_first_matching_rule_wins():
    session = make_session()
    setup_account(session)
    session.add(MerchantRule(match_pattern="coffee", clean_name="Generic Coffee Shop"))
    session.add(MerchantRule(match_pattern="thinking cup", clean_name="Thinking Cup"))
    session.commit()
    txn = make_transaction(session, "AplPay THINKING CUP Boston Coffee")

    apply_merchant_rules(session)

    session.refresh(txn)
    assert txn.clean_description == "Generic Coffee Shop"
