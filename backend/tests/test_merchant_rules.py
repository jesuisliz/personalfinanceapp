import asyncio
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main

from app.categories.apply import apply_all_rules, apply_merchant_rules, find_matching_rule
from app.db import Base
from app.models import Account, Category, CategoryRule, MerchantRule, Transaction


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


def test_find_matching_rule_sorts_by_id_not_input_order():
    newer = MerchantRule(id=5, match_pattern="kura", clean_name="A")
    older = MerchantRule(id=2, match_pattern="kura rev", clean_name="B")

    assert find_matching_rule([newer, older], "SQ *KURA REVOLVING", 1) is older


def test_find_matching_rule_account_tier_beats_older_global():
    global_rule = MerchantRule(id=1, match_pattern="payment", clean_name="Global")
    account_rule = MerchantRule(id=9, match_pattern="payment", clean_name="Scoped", account_id=1)
    rules = [global_rule, account_rule]

    assert find_matching_rule(rules, "PAYMENT - THANK YOU", 1) is account_rule
    assert find_matching_rule(rules, "PAYMENT - THANK YOU", 2) is global_rule


def test_find_matching_rule_unsaved_candidate_is_last_in_its_tier():
    saved = MerchantRule(id=3, match_pattern="kura", clean_name="Saved")
    global_candidate = MerchantRule(id=None, match_pattern="kura", clean_name="Candidate")
    scoped_candidate = MerchantRule(id=None, match_pattern="kura", clean_name="Candidate", account_id=1)

    assert find_matching_rule([global_candidate, saved], "SQ *KURA", 1) is saved
    assert find_matching_rule([saved, scoped_candidate], "SQ *KURA", 1) is scoped_candidate


def test_find_matching_rule_returns_none_when_nothing_matches():
    rules = [MerchantRule(id=1, match_pattern="kura", clean_name="Kura")]

    assert find_matching_rule(rules, "WALMART", 1) is None


def test_apply_all_rules_merchant_rule_wins_over_category_rule():
    session = make_session()
    account = setup_account(session)
    bank_category = Category(name="Dining")
    merchant_category = Category(name="Utilities")
    session.add_all([bank_category, merchant_category])
    session.commit()
    session.add(CategoryRule(institution="Chase", raw_category="Food & Drink", category_id=bank_category.id))
    session.add(MerchantRule(match_pattern="cmp", clean_name="CMP", category_id=merchant_category.id))
    session.commit()
    txn = make_transaction(session, "CMP ELECTRIC BILL", account_id=account.id)
    txn.raw_category = "Food & Drink"
    session.commit()

    apply_all_rules(session)

    session.refresh(txn)
    assert txn.clean_description == "CMP"
    assert txn.category_id == merchant_category.id


def test_startup_applies_merchant_rules_before_category_rules(monkeypatch):
    """The app's lifespan must use the import pipeline's order (LLD 4.5)."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    account = Account(name="Startup Card", institution="StartupBank", account_type="credit_card")
    bank_category = Category(name="Startup Bank Category")
    merchant_category = Category(name="Startup Merchant Category")
    session.add_all([account, bank_category, merchant_category])
    session.commit()
    session.add(CategoryRule(institution="StartupBank", raw_category="Food", category_id=bank_category.id))
    session.add(MerchantRule(match_pattern="cmp", clean_name="CMP", category_id=merchant_category.id))
    txn = make_transaction(session, "CMP ELECTRIC BILL", account_id=account.id)
    txn.raw_category = "Food"
    bank_only = make_transaction(session, "LOCAL DINER", account_id=account.id)
    bank_only.raw_category = "Food"
    session.commit()
    txn_id, expected_category_id = txn.id, merchant_category.id
    bank_only_id, bank_category_id = bank_only.id, bank_category.id
    session.close()

    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main, "get_session", TestSession)

    async def run_startup():
        async with main.lifespan(main.app):
            pass

    asyncio.run(run_startup())

    with TestSession() as check:
        assert check.get(Transaction, txn_id).category_id == expected_category_id
        assert check.get(Transaction, bank_only_id).category_id == bank_category_id
