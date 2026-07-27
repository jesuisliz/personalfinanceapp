from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.categories.apply import apply_category_rules, apply_merchant_rules
from app.categories.seed import seed_categories
from app.db import get_session, init_db
from app.routers import (
    accounts,
    categories,
    chat,
    dashboard,
    imports,
    merchant_rules,
    planning,
    transactions,
    transfer_matches,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    session = get_session()
    try:
        seed_categories(session)
        apply_category_rules(session)
        apply_merchant_rules(session)
    finally:
        session.close()
    yield


app = FastAPI(title="Personal Finance App", lifespan=lifespan)

# Local-only app; the frontend dev server is the only expected caller.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(imports.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(merchant_rules.router)
app.include_router(transfer_matches.router)
app.include_router(dashboard.router)
app.include_router(chat.router)
app.include_router(planning.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
