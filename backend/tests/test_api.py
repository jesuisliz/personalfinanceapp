from datetime import date, timedelta
from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Account, Transaction

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
