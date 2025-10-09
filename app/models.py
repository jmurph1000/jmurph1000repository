from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class AccountTypeEnum(str):
    CORPORATE = "corporate"
    CUSTOMER = "customer"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger, "sqlite"), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)  # values from AccountTypeEnum
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    balances: Mapped[list[DailyBalance]] = relationship("DailyBalance", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("name", "account_type", name="uq_accounts_name_type"),
        Index("ix_accounts_type_name", "account_type", "name"),
    )


class DailyBalance(Base):
    __tablename__ = "daily_balances"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger, "sqlite"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    account: Mapped[Account] = relationship("Account", back_populates="balances")

    __table_args__ = (
        UniqueConstraint("account_id", "as_of_date", name="uq_balance_account_date"),
        Index("ix_balances_date_account", "as_of_date", "account_id"),
        CheckConstraint("opening_balance is not null", name="ck_opening_balance_not_null"),
    )


class SecurityPosition(Base):
    __tablename__ = "security_positions"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger, "sqlite"), primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    security_type: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    market_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    __table_args__ = (
        UniqueConstraint("as_of_date", "security_type", "symbol", name="uq_security_date_type_symbol"),
        Index("ix_security_date_type", "as_of_date", "security_type"),
    )
