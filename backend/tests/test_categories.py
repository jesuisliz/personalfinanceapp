from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.categories.seed import SEED_TAXONOMY, seed_categories
from app.db import Base
from app.models import Category, CategoryRule


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


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
