from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    institution: Mapped[str] = mapped_column(String, nullable=False)
    account_type: Mapped[str] = mapped_column(String, nullable=False)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)


class CategoryRule(Base):
    __tablename__ = "category_rules"
    __table_args__ = (UniqueConstraint("institution", "raw_category", "account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution: Mapped[str] = mapped_column(String, nullable=False)
    raw_category: Mapped[str] = mapped_column(String, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    # When set, this rule overrides the institution-wide mapping for just this one
    # account - needed when one account's raw export reuses a raw_category (e.g.
    # BofA's "Refunds/Adjustments") for something that means something different
    # on that particular account than it does elsewhere at the same institution.
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)


class MerchantRule(Base):
    __tablename__ = "merchant_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_pattern: Mapped[str] = mapped_column(String, nullable=False)
    clean_name: Mapped[str] = mapped_column(String, nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    # When set, this rule only matches transactions on this one account - needed
    # for generic bank statement text (e.g. "PAYMENT - THANK YOU") that carries no
    # identifying info, so a global rule could otherwise mislabel a different
    # account's transactions that happen to reuse the same generic text.
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("account_id", "source_row_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_category: Mapped[str | None] = mapped_column(String, nullable=True)
    memo: Mapped[str | None] = mapped_column(String, nullable=True)
    source_row_hash: Mapped[str] = mapped_column(String, nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    clean_description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Free-form, user-entered only - distinct from `memo`, which is bank-supplied at import time.
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class TransferMatch(Base):
    __tablename__ = "transfer_matches"
    __table_args__ = (UniqueConstraint("transaction_id_a", "transaction_id_b"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id_a: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    transaction_id_b: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="suggested")


class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    target_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    saved_so_far_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    # JSON-encoded list[ToolCallOut]; null for user messages, which never have tool calls.
    tool_calls_json: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CurrentBalance(Base):
    """Single manually-entered total (savings/cash on hand) the user keeps up to date
    themselves. The app has no way to derive a real current balance from imported
    transactions alone -- every CSV import is a bounded date range, never full account
    history, so summing transactions gives a net change, not a starting point."""

    __tablename__ = "current_balance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
