from datetime import date, timedelta
from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Account, Category, MerchantRule, Transaction

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def make_client() -> TestClient:
    """Fresh in-memory DB per test; see make_client_and_sessionmaker."""
    client, _ = make_client_and_sessionmaker()
    return client


def make_client_and_sessionmaker() -> tuple[TestClient, sessionmaker]:
    """Fresh in-memory DB per test via dependency override; also returns the sessionmaker for direct inserts.

    Deliberately does NOT use `with TestClient(app) as client:` — that would
    trigger the app's startup event (init_db against the real DATABASE_PATH),
    which would create a real finance.db file as a side effect of running
    tests. Routes work fine without the lifespan firing; only startup/shutdown
    hooks are skipped.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def _get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), TestSessionLocal


def test_health():
    client = make_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_import_then_list_accounts_and_transactions():
    client = make_client()
    resp = client.post(
        "/imports",
        files={"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["rows_inserted"] == 3

    accounts_resp = client.get("/accounts")
    assert accounts_resp.status_code == 200
    assert len(accounts_resp.json()) == 1
    assert accounts_resp.json()[0]["name"] == "Chase Sapphire (...3403)"

    txns_resp = client.get("/transactions")
    assert txns_resp.status_code == 200
    assert len(txns_resp.json()) == 3


def test_reimport_via_api_inserts_zero_new_rows():
    client = make_client()
    files = {"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")}
    client.post("/imports", files=files)
    resp = client.post("/imports", files=files)
    assert resp.json()["rows_inserted"] == 0
    assert resp.json()["rows_skipped_as_duplicate"] == 3


def test_unmatched_filename_returns_400_not_500():
    client = make_client()
    resp = client.post("/imports", files={"file": ("SomeRandomBank.csv", b"a,b\n1,2\n", "text/csv")})
    assert resp.status_code == 400
    assert "SomeRandomBank.csv" in resp.json()["detail"]


def test_transactions_filter_by_account_id():
    client = make_client()
    client.post(
        "/imports", files={"file": ("ExportData_BOA.csv", read_fixture("boa_sample.csv"), "text/csv")}
    )
    accounts = client.get("/accounts").json()
    credit_card_account = next(a for a in accounts if a["account_type"] == "credit_card")

    resp = client.get(f"/transactions?account_id={credit_card_account['id']}")
    assert resp.status_code == 200
    assert len(resp.json()) > 0
    for txn in resp.json():
        assert txn["account_id"] == credit_card_account["id"]


def test_create_category_then_assign_to_transaction():
    client = make_client()
    client.post(
        "/imports",
        files={"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")},
    )
    txn_id = client.get("/transactions").json()[0]["id"]

    category_resp = client.post("/categories", json={"name": "Test Category"})
    assert category_resp.status_code == 200
    category_id = category_resp.json()["id"]

    patch_resp = client.patch(f"/transactions/{txn_id}", json={"category_id": category_id})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["category_id"] == category_id


def test_assigning_nonexistent_category_returns_400():
    client = make_client()
    client.post(
        "/imports",
        files={"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")},
    )
    txn_id = client.get("/transactions").json()[0]["id"]

    resp = client.patch(f"/transactions/{txn_id}", json={"category_id": 9999})
    assert resp.status_code == 400


def test_patch_transaction_sets_clean_description_and_is_transfer():
    client = make_client()
    client.post(
        "/imports",
        files={"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")},
    )
    txn_id = client.get("/transactions").json()[0]["id"]

    resp = client.patch(
        f"/transactions/{txn_id}", json={"clean_description": "DoorDash", "is_transfer": True}
    )
    assert resp.status_code == 200
    assert resp.json()["clean_description"] == "DoorDash"
    assert resp.json()["is_transfer"] is True


def test_patch_transaction_sets_note():
    client = make_client()
    client.post(
        "/imports",
        files={"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")},
    )
    txn_id = client.get("/transactions").json()[0]["id"]
    assert client.get("/transactions").json()[0]["note"] is None

    resp = client.patch(f"/transactions/{txn_id}", json={"note": "Sent for my sister, not mortgage"})
    assert resp.status_code == 200
    assert resp.json()["note"] == "Sent for my sister, not mortgage"

    # Clearing it back to null must also work.
    resp = client.patch(f"/transactions/{txn_id}", json={"note": None})
    assert resp.status_code == 200
    assert resp.json()["note"] is None


def test_duplicate_category_name_returns_400():
    client = make_client()
    client.post("/categories", json={"name": "Dining"})
    resp = client.post("/categories", json={"name": "Dining"})
    assert resp.status_code == 400


def test_rename_category():
    client = make_client()
    create_resp = client.post("/categories", json={"name": "Old Name"})
    category_id = create_resp.json()["id"]

    resp = client.patch(f"/categories/{category_id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_merchant_rule_applies_immediately_to_existing_transactions():
    client = make_client()
    client.post(
        "/imports",
        files={"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")},
    )

    rule_resp = client.post("/merchant-rules", json={"match_pattern": "doordash", "clean_name": "DoorDash"})
    assert rule_resp.status_code == 200

    txns = client.get("/transactions").json()
    doordash_txn = next(t for t in txns if "DOORDASH" in t["description"])
    assert doordash_txn["clean_description"] == "DoorDash"


def test_merchant_rule_with_invalid_category_returns_400():
    client = make_client()
    resp = client.post(
        "/merchant-rules", json={"match_pattern": "test", "clean_name": "Test", "category_id": 9999}
    )
    assert resp.status_code == 400


def test_transfer_detection_finds_real_boa_pair_and_confirm_flags_both():
    client = make_client()
    client.post(
        "/imports", files={"file": ("ExportData_BOA.csv", read_fixture("boa_sample.csv"), "text/csv")}
    )

    detect_resp = client.post("/transfer-matches/detect")
    assert detect_resp.status_code == 200
    suggested = detect_resp.json()
    assert len(suggested) >= 1

    match = suggested[0]
    confirm_resp = client.patch(f"/transfer-matches/{match['id']}", json={"status": "confirmed"})
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "confirmed"

    txns = client.get("/transactions").json()
    txn_a = next(t for t in txns if t["id"] == match["transaction_id_a"])
    txn_b = next(t for t in txns if t["id"] == match["transaction_id_b"])
    assert txn_a["is_transfer"] is True
    assert txn_b["is_transfer"] is True
    assert txn_a["amount_cents"] == -txn_b["amount_cents"]


def test_chat_without_api_key_returns_400_not_crash(monkeypatch):
    monkeypatch.setattr("app.chat.service.OPENAI_API_KEY", "")
    client = make_client()
    resp = client.post("/chat", json={"message": "hi", "history": []})
    assert resp.status_code == 400
    assert "OPENAI_API_KEY" in resp.json()["detail"]


def test_goal_crud_lifecycle():
    client = make_client()

    create_resp = client.post(
        "/goals", json={"name": "Hawaii Vacation", "target_amount_cents": 400000, "saved_so_far_cents": 50000}
    )
    assert create_resp.status_code == 200
    goal = create_resp.json()
    assert goal["name"] == "Hawaii Vacation"
    assert goal["saved_so_far_cents"] == 50000

    list_resp = client.get("/goals")
    assert len(list_resp.json()) == 1

    patch_resp = client.patch(f"/goals/{goal['id']}", json={"saved_so_far_cents": 100000})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["saved_so_far_cents"] == 100000

    delete_resp = client.delete(f"/goals/{goal['id']}")
    assert delete_resp.status_code == 204
    assert client.get("/goals").json() == []


def test_goal_not_found_returns_404():
    client = make_client()
    resp = client.patch("/goals/9999", json={"saved_so_far_cents": 100})
    assert resp.status_code == 404


def test_balance_not_configured_then_set():
    client = make_client()

    get_resp = client.get("/balance")
    assert get_resp.status_code == 200
    assert get_resp.json()["configured"] is False

    put_resp = client.put("/balance", json={"amount_cents": 500000})
    assert put_resp.status_code == 200
    assert put_resp.json()["configured"] is True
    assert put_resp.json()["amount_cents"] == 500000

    get_again = client.get("/balance")
    assert get_again.json()["amount_cents"] == 500000


def test_runway_reflects_real_imported_expenses_and_configured_balance():
    client = make_client()
    client.post(
        "/imports", files={"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")}
    )
    client.put("/balance", json={"amount_cents": 1000000})

    resp = client.get("/runway?months=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["balance_configured"] is True
    assert body["current_balance_cents"] == 1000000


def test_scenario_with_unknown_category_returns_400():
    client = make_client()
    resp = client.post(
        "/scenario", json={"category_name": "Not Real", "reduction_percent": 25, "months": 6}
    )
    assert resp.status_code == 400


def test_scenario_against_goal_returns_goal_projection():
    client = make_client()
    client.post(
        "/imports", files={"file": ("Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"), "text/csv")}
    )
    goal_resp = client.post("/goals", json={"name": "Test Goal", "target_amount_cents": 1000000})
    goal_id = goal_resp.json()["id"]

    resp = client.post(
        "/scenario",
        json={"category_name": "Uncategorized", "reduction_percent": 50, "months": 1, "goal_id": goal_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal_projection"] is not None
    assert body["goal_projection"]["goal_id"] == goal_id
    assert body["runway"] is None


def insert_transactions(session_factory: sessionmaker, rows: list[tuple[int, date]]) -> None:
    """Insert one account plus a transaction per (id, date) pair, in the given order."""
    with session_factory() as session:
        session.add(Account(id=1, name="Test Checking", institution="Test", account_type="checking"))
        session.add_all(
            Transaction(
                id=txn_id,
                account_id=1,
                date=txn_date,
                description=f"Txn {txn_id}",
                amount_cents=-100,
                source_row_hash=f"hash-{txn_id}",
            )
            for txn_id, txn_date in rows
        )
        session.commit()


def returned_ids(resp) -> list[int]:
    assert resp.status_code == 200, resp.text
    return [t["id"] for t in resp.json()]


# Ids deliberately out of date order, and ids 1 and 4 share a date.
# Newest-first with id DESC tie-break: 3, 5, 4, 1, 2.
MIXED_ROWS = [
    (1, date(2026, 3, 5)),
    (2, date(2026, 3, 1)),
    (3, date(2026, 3, 10)),
    (4, date(2026, 3, 5)),
    (5, date(2026, 3, 8)),
]


def test_list_transactions_returns_all_rows_when_limit_omitted():
    """Regression: the Transactions tab silently lost every row past 1000.

    A larger fixed cap would still pass this test alone; the schema test below
    is what rules out any default or maximum on `limit`.
    """
    client, session_factory = make_client_and_sessionmaker()
    start = date(2023, 1, 1)
    rows = [(i, start + timedelta(days=i)) for i in range(1, 1002)]
    insert_transactions(session_factory, rows)

    ids = returned_ids(client.get("/transactions"))

    assert len(ids) == 1001
    assert ids == list(range(1001, 0, -1))


def test_list_transactions_accepts_limit_above_old_max():
    client, session_factory = make_client_and_sessionmaker()
    start = date(2023, 1, 1)
    insert_transactions(session_factory, [(i, start + timedelta(days=i)) for i in range(1, 1002)])

    assert len(returned_ids(client.get("/transactions?limit=1001"))) == 1001


@pytest.mark.parametrize(
    "query, expected_ids",
    [
        ("", [3, 5, 4, 1, 2]),
        ("?limit=3", [3, 5, 4]),
        ("?offset=2", [4, 1, 2]),
        ("?limit=2&offset=1", [5, 4]),
        ("?date_from=2026-03-05&date_to=2026-03-08", [5, 4, 1]),
        ("?date_from=2026-03-05", [3, 5, 4, 1]),
        ("?date_to=2026-03-05", [4, 1, 2]),
    ],
)
def test_list_transactions_order_and_paging(query, expected_ids):
    client, session_factory = make_client_and_sessionmaker()
    insert_transactions(session_factory, MIXED_ROWS)

    assert returned_ids(client.get(f"/transactions{query}")) == expected_ids


@pytest.mark.parametrize("bad_limit", ["0", "-1", "", "abc"])
def test_list_transactions_rejects_invalid_limit(bad_limit):
    client = make_client()

    assert client.get(f"/transactions?limit={bad_limit}").status_code == 422


def test_list_transactions_rejects_negative_offset():
    client = make_client()

    assert client.get("/transactions?offset=-1").status_code == 422


def test_list_transactions_limit_has_no_default_or_maximum():
    """Guards the no-cap rule directly: any fixed default or `le` bound reintroduces the silent-truncation bug."""
    params = make_client().get("/openapi.json").json()["paths"]["/transactions"]["get"]["parameters"]
    limit_schema = next(p for p in params if p["name"] == "limit")["schema"]

    assert limit_schema.get("default") is None
    assert "maximum" not in str(limit_schema)


def chase_upload(*rows: tuple[str, str, str]) -> dict:
    lines = ["Transaction Date,Post Date,Description,Category,Type,Amount,Memo"]
    lines += [f"{day},{day},{description},Shopping,Sale,{amount}," for day, description, amount in rows]
    body = ("\n".join(lines) + "\n").encode()
    return {"file": ("Chase3403_Activity_20260726.csv", body, "text/csv")}


def test_import_holds_suspects_and_accepts_repeated_accept_hashes_fields():
    client = make_client()
    first = client.post(
        "/imports",
        files=chase_upload(
            ("07/10/2026", "HANNAFORD", "-34.50"),
            ("07/12/2026", "SHELL", "-40.00"),
            ("07/15/2026", "NETFLIX", "-15.49"),
        ),
    )
    assert first.json()["rows_held_as_suspected_duplicate"] == 0
    assert first.json()["suspected_duplicates"] == []

    new_rows = (
        ("07/11/2026", "HANNAFORD #8354", "-34.50"),
        ("07/14/2026", "SHELL OIL", "-40.00"),
        ("07/15/2026", "NETFLIX.COM", "-15.49"),
    )
    held = client.post("/imports", files=chase_upload(*new_rows)).json()

    assert held["rows_held_as_suspected_duplicate"] == 3
    hannaford = next(s for s in held["suspected_duplicates"] if s["description"] == "HANNAFORD #8354")
    assert set(hannaford) == {
        "row_hash", "account_name", "date", "description", "amount_cents",
        "existing_id", "existing_date", "existing_description",
    }
    assert hannaford["date"] == "2026-07-11"
    assert hannaford["existing_date"] == "2026-07-10"
    assert hannaford["existing_description"] == "HANNAFORD"
    existing = next(t for t in client.get("/transactions").json() if t["description"] == "HANNAFORD")
    assert hannaford["existing_id"] == existing["id"]
    assert hannaford["account_name"] == "Chase Sapphire (...3403)"
    assert hannaford["amount_cents"] == -3450
    assert len(hannaford["row_hash"]) == 64

    accept = [s["row_hash"] for s in held["suspected_duplicates"] if s["description"] != "SHELL OIL"]
    resp = client.post("/imports", files=chase_upload(*new_rows), data={"accept_hashes": accept})

    assert resp.status_code == 200
    assert resp.json()["rows_inserted"] == 2
    assert [s["description"] for s in resp.json()["suspected_duplicates"]] == ["SHELL OIL"]


# --- Remember a category edit as a merchant rule (docs/lld_edit_creates_merchant_rule_claude.md) ---

DINING, TRAVEL, GROCERIES = 1, 2, 3


def make_rule_client():
    """Two accounts, three categories and three KURA rows: the edited source row
    (Dining, account 1), a blank sibling on account 1, and a blank row on account 2."""
    client, Session = make_client_and_sessionmaker()
    with Session() as session:
        session.add_all([
            Account(id=1, name="Card A", institution="Chase", account_type="credit_card"),
            Account(id=2, name="Card B", institution="Amex", account_type="credit_card"),
            Category(id=DINING, name="Dining"),
            Category(id=TRAVEL, name="Travel"),
            Category(id=GROCERIES, name="Groceries"),
        ])
        session.add_all([
            make_row(1, 1, "SQ *KURA REVOLVING SUSHI", date(2026, 1, 5), category_id=DINING),
            make_row(2, 1, "SQ *KURA REVOLVING SUSHI #2", date(2026, 1, 4)),
            make_row(3, 2, "SQ *KURA REVOLVING", date(2026, 1, 3)),
        ])
        session.commit()
    return client, Session


def make_row(txn_id, account_id, description, txn_date, category_id=None, clean=None):
    return Transaction(
        id=txn_id,
        account_id=account_id,
        date=txn_date,
        description=description,
        amount_cents=-1000,
        source_row_hash=f"hash-{txn_id}",
        category_id=category_id,
        clean_description=clean,
    )


def add_existing_rule(Session, pattern, category_id, account_id=None) -> int:
    with Session() as session:
        rule = MerchantRule(match_pattern=pattern, clean_name="Existing", category_id=category_id, account_id=account_id)
        session.add(rule)
        session.commit()
        return rule.id


def rule_count(Session) -> int:
    with Session() as session:
        return session.scalar(select(func.count()).select_from(MerchantRule))


def get_row(Session, txn_id) -> Transaction:
    with Session() as session:
        return session.get(Transaction, txn_id)


def preview(client, **overrides):
    body = {"source_transaction_id": 1, "match_pattern": None, "category_id": DINING, "this_account_only": False}
    return client.post("/merchant-rules/preview", json={**body, **overrides})


def create_from_source(client, **overrides):
    body = {
        "match_pattern": "SQ *KURA",
        "clean_name": "Kura Sushi",
        "category_id": DINING,
        "source_transaction_id": 1,
        "this_account_only": False,
    }
    return client.post("/merchant-rules", json={**body, **overrides})


def test_rule_preview_null_pattern_uses_suggestion_and_returns_full_response():
    client, _ = make_rule_client()

    resp = preview(client)

    assert resp.status_code == 200
    assert resp.json() == {
        "match_pattern": "SQ *KURA",
        "matches_source": True,
        "conflicting_rule": None,
        "would_name_count": 3,
        "would_categorize_count": 2,
        "category_mismatch_count": 0,
        "sample": [
            {"id": 1, "date": "2026-01-05", "description": "SQ *KURA REVOLVING SUSHI", "category_name": "Dining"},
            {"id": 2, "date": "2026-01-04", "description": "SQ *KURA REVOLVING SUSHI #2", "category_name": None},
            {"id": 3, "date": "2026-01-03", "description": "SQ *KURA REVOLVING", "category_name": None},
        ],
    }


def test_rule_preview_padded_pattern_is_evaluated_stripped():
    client, _ = make_rule_client()

    resp = preview(client, match_pattern="  KURA  ")

    assert resp.json()["match_pattern"] == "KURA"


def test_rule_preview_reports_conflicting_rule():
    client, Session = make_rule_client()
    rule_id = add_existing_rule(Session, "SQ *KURA REV", GROCERIES)

    resp = preview(client, match_pattern="SQ *KURA")

    assert resp.json()["conflicting_rule"] == {
        "id": rule_id, "match_pattern": "SQ *KURA REV", "clean_name": "Existing",
        "category_id": GROCERIES, "account_id": None,
    }


def test_rule_preview_is_read_only():
    client, Session = make_rule_client()

    resp = preview(client, match_pattern="SQ *KURA")

    assert resp.status_code == 200
    assert rule_count(Session) == 0
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Transaction)) == 3
    blank = get_row(Session, 2)
    assert blank.clean_description is None
    assert blank.category_id is None


def test_rule_preview_unknown_source_returns_404():
    client, _ = make_rule_client()

    resp = preview(client, source_transaction_id=999)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "source_not_found"
    assert resp.json()["detail"]["message"]


def test_rule_preview_source_category_changed_returns_409():
    client, _ = make_rule_client()

    resp = preview(client, category_id=TRAVEL)

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "source_category_changed"
    assert resp.json()["detail"]["message"]


@pytest.mark.parametrize("pattern", ["", "   "])
def test_rule_preview_blank_pattern_returns_422(pattern):
    client, _ = make_rule_client()

    assert preview(client, match_pattern=pattern).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"match_pattern": "", "clean_name": "DoorDash"},
        {"match_pattern": "   ", "clean_name": "DoorDash"},
        {"match_pattern": "doordash", "clean_name": "  "},
    ],
)
def test_create_rule_without_source_rejects_blank_text(body):
    client, Session = make_rule_client()

    assert client.post("/merchant-rules", json=body).status_code == 422
    assert rule_count(Session) == 0


def test_create_rule_without_source_stores_stripped_text():
    client, _ = make_rule_client()

    resp = client.post("/merchant-rules", json={"match_pattern": "  DoorDash  ", "clean_name": " DoorDash "})

    assert resp.status_code == 200
    assert resp.json()["match_pattern"] == "DoorDash"
    assert resp.json()["clean_name"] == "DoorDash"


def test_create_rule_from_source_rejects_account_id_in_body():
    client, Session = make_rule_client()

    assert create_from_source(client, account_id=1).status_code == 422
    assert rule_count(Session) == 0


def test_create_rule_from_source_requires_category():
    client, Session = make_rule_client()

    assert create_from_source(client, category_id=None).status_code == 422
    assert rule_count(Session) == 0


def test_create_rule_from_source_applies_to_all_accounts():
    client, Session = make_rule_client()

    resp = create_from_source(client)

    assert resp.status_code == 200
    assert resp.json()["account_id"] is None
    for txn_id in (2, 3):
        row = get_row(Session, txn_id)
        assert row.clean_description == "Kura Sushi"
        assert row.category_id == DINING


def test_create_rule_from_source_this_account_only_stores_source_account():
    client, Session = make_rule_client()

    resp = create_from_source(client, this_account_only=True)

    assert resp.status_code == 200
    assert resp.json()["account_id"] == 1
    assert get_row(Session, 2).clean_description == "Kura Sushi"
    assert get_row(Session, 3).clean_description is None


def test_create_rule_from_unknown_source_returns_404():
    client, Session = make_rule_client()

    resp = create_from_source(client, source_transaction_id=999)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "source_not_found"
    assert resp.json()["detail"]["message"]
    assert rule_count(Session) == 0


def test_create_rule_source_category_changed_beats_non_matching_pattern():
    client, Session = make_rule_client()

    resp = create_from_source(client, category_id=TRAVEL, match_pattern="WALMART")

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "source_category_changed"
    assert resp.json()["detail"]["message"]
    assert rule_count(Session) == 0


def test_create_rule_non_matching_pattern_returns_400_even_when_a_rule_owns_the_source():
    client, Session = make_rule_client()
    add_existing_rule(Session, "SQ *KURA REV", GROCERIES)

    resp = create_from_source(client, match_pattern="WALMART")

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "pattern_not_matching_source"
    assert resp.json()["detail"]["message"]
    assert rule_count(Session) == 1


def test_create_rule_conflict_returns_409_with_rule():
    client, Session = make_rule_client()
    rule_id = add_existing_rule(Session, "SQ *KURA REV", GROCERIES)

    resp = create_from_source(client)

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "conflict"
    assert detail["message"]
    assert detail["rule"] == {
        "id": rule_id, "match_pattern": "SQ *KURA REV", "clean_name": "Existing",
        "category_id": GROCERIES, "account_id": None,
    }
    assert rule_count(Session) == 1


def test_create_rule_conflict_beats_category_mismatch():
    client, Session = make_rule_client()
    add_existing_rule(Session, "SQ *KURA REV", GROCERIES)
    with Session() as session:
        session.add(make_row(4, 1, "SQ *KURA TRAVEL", date(2026, 1, 1), category_id=TRAVEL))
        session.commit()

    resp = create_from_source(client)

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "conflict"


def test_create_rule_category_mismatch_returns_409_with_count_and_sample():
    client, Session = make_rule_client()
    with Session() as session:
        session.add(make_row(4, 1, "SQ *KURA TRAVEL", date(2026, 1, 1), category_id=TRAVEL, clean="My name"))
        session.commit()

    resp = create_from_source(client)

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "category_mismatch"
    assert detail["message"]
    assert detail["count"] == 1
    assert detail["sample"][0] == {
        "id": 4, "date": "2026-01-01", "description": "SQ *KURA TRAVEL", "category_name": "Travel"
    }
    assert rule_count(Session) == 0
    assert get_row(Session, 2).clean_description is None


def test_delete_rule_keeps_rows_it_filled():
    client, Session = make_rule_client()
    rule_id = create_from_source(client).json()["id"]

    resp = client.delete(f"/merchant-rules/{rule_id}")

    assert resp.status_code == 204
    assert rule_count(Session) == 0
    for txn_id in (2, 3):
        row = get_row(Session, txn_id)
        assert row.clean_description == "Kura Sushi"
        assert row.category_id == DINING
    assert client.delete(f"/merchant-rules/{rule_id}").status_code == 404


def test_list_rules_reports_match_counts_and_delete_unshadows_the_next_rule():
    """Rows 1-3 all contain "KURA"; only rows 1 and 2 contain the longer pattern,
    which is shadowed by the lower-id global rule until that rule is deleted."""
    client, Session = make_rule_client()
    broad = add_existing_rule(Session, "KURA", DINING)
    narrow = add_existing_rule(Session, "SQ *KURA REVOLVING SUSHI", TRAVEL)

    before = client.get("/merchant-rules")

    assert before.status_code == 200
    assert before.json() == [
        {"id": broad, "match_pattern": "KURA", "clean_name": "Existing", "category_id": DINING,
         "account_id": None, "match_count": 3},
        {"id": narrow, "match_pattern": "SQ *KURA REVOLVING SUSHI", "clean_name": "Existing",
         "category_id": TRAVEL, "account_id": None, "match_count": 0},
    ]

    rows_before = [(r.clean_description, r.category_id) for r in (get_row(Session, i) for i in (1, 2, 3))]
    assert client.delete(f"/merchant-rules/{broad}").status_code == 204

    after = client.get("/merchant-rules").json()
    assert [(r["id"], r["match_count"]) for r in after] == [(narrow, 2)]
    rows_after = [(r.clean_description, r.category_id) for r in (get_row(Session, i) for i in (1, 2, 3))]
    assert rows_after == rows_before
    assert client.delete(f"/merchant-rules/{broad}").status_code == 404


def test_list_rules_reports_zero_for_a_rule_created_after_counting(monkeypatch):
    """The count and the list are two reads; a rule saved between them (another
    window) must list with 0, not crash the endpoint with a KeyError."""
    client, Session = make_rule_client()
    rule_id = add_existing_rule(Session, "KURA", DINING)
    monkeypatch.setattr("app.routers.merchant_rules.count_rule_wins", lambda db: {})

    resp = client.get("/merchant-rules")

    assert resp.status_code == 200
    assert [(r["id"], r["match_count"]) for r in resp.json()] == [(rule_id, 0)]


def test_list_rules_with_no_rules_is_empty_list():
    client, _ = make_rule_client()

    resp = client.get("/merchant-rules")

    assert resp.status_code == 200
    assert resp.json() == []


def add_row(Session, *args, **kwargs):
    with Session() as session:
        session.add(make_row(*args, **kwargs))
        session.commit()


@pytest.mark.parametrize("description", ["AplPay  BLUE BOTTLE", "BLUE BOTTLE  DES:X"])
def test_rule_preview_suggested_pattern_is_normalized(description):
    """A raw cut here is " BLUE BOTTLE" or "BLUE BOTTLE "; preview must evaluate and report
    the stripped pattern create would store. Row 5 matches only the stripped pattern."""
    client, Session = make_rule_client()
    add_row(Session, 4, 1, description, date(2026, 1, 6), category_id=DINING)
    add_row(Session, 5, 1, "SQ *BLUE BOTTLE", date(2026, 1, 7))

    resp = preview(client, source_transaction_id=4)

    assert resp.status_code == 200
    assert resp.json()["match_pattern"] == "BLUE BOTTLE"
    assert resp.json()["would_name_count"] == 2


def test_rule_preview_blank_description_without_pattern_returns_422():
    client, Session = make_rule_client()
    add_row(Session, 4, 1, "   ", date(2026, 1, 6), category_id=DINING)

    resp = preview(client, source_transaction_id=4)

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "no_suggested_pattern"
    assert resp.json()["detail"]["message"]


def test_create_rule_from_source_with_unknown_category_returns_400():
    """SQLite FKs are off, so a source row can hold a category id that doesn't exist."""
    client, Session = make_rule_client()
    add_row(Session, 4, 1, "ZZ MYSTERY SHOP", date(2026, 1, 6), category_id=99)

    resp = create_from_source(client, source_transaction_id=4, category_id=99, match_pattern="ZZ MYSTERY")

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "category_not_found"
    assert resp.json()["detail"]["message"]
    assert rule_count(Session) == 0


def test_create_rule_from_source_scoped_to_unknown_account_returns_400():
    client, Session = make_rule_client()
    add_row(Session, 4, 7, "SQ *KURA REVOLVING SUSHI", date(2026, 1, 6), category_id=DINING)

    resp = create_from_source(client, source_transaction_id=4, this_account_only=True)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "account_not_found"
    assert resp.json()["detail"]["message"]
    assert rule_count(Session) == 0


def test_create_rule_without_source_keeps_account_id():
    client, Session = make_rule_client()

    resp = client.post("/merchant-rules", json={"match_pattern": "KURA", "clean_name": "Kura", "account_id": 2})

    assert resp.status_code == 200
    assert resp.json()["account_id"] == 2
    assert get_row(Session, 3).clean_description == "Kura"
    assert get_row(Session, 2).clean_description is None


def test_create_rule_without_source_unknown_account_returns_400():
    client, Session = make_rule_client()

    resp = client.post("/merchant-rules", json={"match_pattern": "KURA", "clean_name": "Kura", "account_id": 999})

    assert resp.status_code == 400
    assert rule_count(Session) == 0


def test_create_rule_from_source_conflicts_with_scoped_rule_on_source_account():
    """An existing rule scoped to the source's account beats a global candidate, and a
    scoped candidate too - the unsaved candidate sorts last in the account tier."""
    client, Session = make_rule_client()
    rule_id = add_existing_rule(Session, "SQ *KURA REV", GROCERIES, account_id=1)

    for this_account_only in (False, True):
        resp = create_from_source(client, this_account_only=this_account_only)

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "conflict"
        assert resp.json()["detail"]["rule"]["id"] == rule_id
    assert rule_count(Session) == 1


def test_create_rule_pattern_not_matching_source_beats_category_mismatch():
    client, Session = make_rule_client()
    add_row(Session, 4, 1, "SQ *KURA TRAVEL", date(2026, 1, 1), category_id=TRAVEL)

    resp = create_from_source(client, match_pattern="KURA TRAVEL")

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "pattern_not_matching_source"
    assert resp.json()["detail"]["message"]
    assert rule_count(Session) == 0


def test_rule_preview_this_account_only_with_mismatch():
    client, Session = make_rule_client()
    add_row(Session, 4, 1, "SQ *KURA TRAVEL", date(2026, 1, 1), category_id=TRAVEL)

    resp = preview(client, this_account_only=True)

    assert resp.status_code == 200
    body = resp.json()
    assert body["would_name_count"] == 3  # rows 1, 2, 4; row 3 is on account 2
    assert body["would_categorize_count"] == 1  # row 2
    assert body["category_mismatch_count"] == 1  # row 4
    assert [row["id"] for row in body["sample"]] == [4, 1, 2]


def test_create_rule_source_category_cleared_returns_409():
    client, Session = make_rule_client()
    with Session() as session:
        session.get(Transaction, 1).category_id = None
        session.commit()

    resp = create_from_source(client)

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "source_category_changed"
    assert resp.json()["detail"]["message"]
    assert rule_count(Session) == 0


@pytest.mark.parametrize("field", ["match_pattern", "clean_name"])
@pytest.mark.parametrize("value", ["", "   "])
def test_create_rule_from_source_rejects_blank_text(field, value):
    client, Session = make_rule_client()

    assert create_from_source(client, **{field: value}).status_code == 422
    assert rule_count(Session) == 0


def test_create_rule_from_source_stores_stripped_text():
    client, Session = make_rule_client()

    resp = create_from_source(client, match_pattern="  SQ *KURA  ", clean_name="  Kura Sushi ")

    assert resp.status_code == 200
    assert resp.json()["match_pattern"] == "SQ *KURA"
    assert resp.json()["clean_name"] == "Kura Sushi"
    assert get_row(Session, 2).clean_description == "Kura Sushi"


def test_create_rule_from_source_on_second_account_scopes_to_that_account():
    client, Session = make_rule_client()
    add_row(Session, 4, 2, "SQ *KURA REVOLVING", date(2026, 1, 6), category_id=DINING)

    resp = create_from_source(client, source_transaction_id=4, this_account_only=True)

    assert resp.status_code == 200
    assert resp.json()["account_id"] == 2
    assert get_row(Session, 3).clean_description == "Kura Sushi"
    assert get_row(Session, 2).clean_description is None


def test_create_rule_from_source_unknown_category_beats_non_matching_pattern():
    client, Session = make_rule_client()
    add_row(Session, 4, 1, "ZZ MYSTERY SHOP", date(2026, 1, 6), category_id=99)

    resp = create_from_source(client, source_transaction_id=4, category_id=99, match_pattern="WALMART")

    assert resp.json()["detail"]["code"] == "category_not_found"


def test_create_rule_from_source_unknown_account_beats_non_matching_pattern():
    client, Session = make_rule_client()
    add_row(Session, 4, 7, "ZZ MYSTERY SHOP", date(2026, 1, 6), category_id=DINING)

    resp = create_from_source(client, source_transaction_id=4, this_account_only=True, match_pattern="WALMART")

    assert resp.json()["detail"]["code"] == "account_not_found"


def test_create_rule_from_source_on_unknown_account_unscoped_is_allowed():
    """A global rule stores no account, so the source's missing account doesn't matter."""
    client, Session = make_rule_client()
    add_row(Session, 4, 7, "ZZ MYSTERY SHOP", date(2026, 1, 6), category_id=DINING)

    resp = create_from_source(client, source_transaction_id=4, match_pattern="ZZ MYSTERY")

    assert resp.status_code == 200
    assert resp.json()["account_id"] is None
