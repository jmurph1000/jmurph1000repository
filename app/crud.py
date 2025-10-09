from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, List, Dict, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Account, DailyBalance, SecurityPosition


def get_or_create_account(session: Session, name: str, account_type: str, **kwargs) -> Account:
    account = session.scalar(select(Account).where(Account.name == name, Account.account_type == account_type))
    if account:
        return account
    account = Account(name=name, account_type=account_type, **kwargs)
    session.add(account)
    session.flush()
    return account


def upsert_daily_balances_from_records(
    session: Session, records: List[Dict[str, Any]], *, account_type_hint: str | None = None
) -> int:
    required_cols = {"as_of_date", "account_name", "opening_balance"}
    upserted = 0
    for rec in records:
        missing = required_cols - set(rec.keys())
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        account_name = str(rec["account_name"]).strip()
        raw_date = rec["as_of_date"]
        if isinstance(raw_date, str):
            as_of = date.fromisoformat(raw_date)
        elif isinstance(raw_date, date):
            as_of = raw_date
        else:
            # openpyxl date serials or others: fallback to str parse
            as_of = date.fromisoformat(str(raw_date))
        opening_balance = Decimal(str(rec["opening_balance"]))
        account_type = str(rec.get("account_type") or account_type_hint or "corporate")

        account = get_or_create_account(session, account_name, account_type)
        existing = session.scalar(
            select(DailyBalance).where(DailyBalance.account_id == account.id, DailyBalance.as_of_date == as_of)
        )
        if existing:
            existing.opening_balance = opening_balance
        else:
            session.add(
                DailyBalance(
                    account_id=account.id, as_of_date=as_of, opening_balance=opening_balance
                )
            )
        upserted += 1
    return upserted


def upsert_security_positions_from_records(session: Session, records: List[Dict[str, Any]]) -> int:
    required = {"as_of_date", "security_type", "symbol", "quantity", "market_value", "currency"}
    upserted = 0
    for rec in records:
        missing = required - set(rec.keys())
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        raw_date = rec["as_of_date"]
        if isinstance(raw_date, str):
            as_of = date.fromisoformat(raw_date)
        elif isinstance(raw_date, date):
            as_of = raw_date
        else:
            as_of = date.fromisoformat(str(raw_date))
        security_type = str(rec["security_type"]) if rec.get("security_type") is not None else ""
        symbol_val = rec.get("symbol")
        symbol = None if symbol_val in (None, "", "nan") else str(symbol_val)
        quantity_val = rec.get("quantity")
        quantity = None if quantity_val in (None, "", "nan") else Decimal(str(quantity_val))
        market_value = Decimal(str(rec["market_value"]))
        currency = str(rec.get("currency") or "USD")

        existing = session.scalar(
            select(SecurityPosition).where(
                SecurityPosition.as_of_date == as_of,
                SecurityPosition.security_type == security_type,
                SecurityPosition.symbol.is_(symbol) if symbol is None else SecurityPosition.symbol == symbol,
            )
        )
        if existing:
            existing.quantity = quantity
            existing.market_value = market_value
            existing.currency = currency
        else:
            session.add(
                SecurityPosition(
                    as_of_date=as_of,
                    security_type=security_type,
                    symbol=symbol,
                    quantity=quantity,
                    market_value=market_value,
                    currency=currency,
                )
            )
        upserted += 1
    return upserted


def get_cash_totals_by_type_for_dates(session: Session, dates: list[date]) -> list[dict[str, Decimal]]:
    # returns list aligned to dates: {date, corporate_total, customer_total}
    results: list[dict[str, Decimal]] = []
    for d in dates:
        corporate_total = (
            session.scalar(
                select(func.coalesce(func.sum(DailyBalance.opening_balance), 0)).join(Account).where(
                    DailyBalance.as_of_date == d, Account.account_type == "corporate"
                )
            )
            or 0
        )
        customer_total = (
            session.scalar(
                select(func.coalesce(func.sum(DailyBalance.opening_balance), 0)).join(Account).where(
                    DailyBalance.as_of_date == d, Account.account_type == "customer"
                )
            )
            or 0
        )
        results.append({"as_of_date": d, "corporate_total": Decimal(str(corporate_total)), "customer_total": Decimal(str(customer_total))})
    return results


def get_security_summary_by_type_for_date(session: Session, d: date) -> dict[str, Decimal]:
    rows = session.execute(
        select(SecurityPosition.security_type, func.coalesce(func.sum(SecurityPosition.market_value), 0)).where(
            SecurityPosition.as_of_date == d
        ).group_by(SecurityPosition.security_type)
    ).all()
    return {row[0]: Decimal(str(row[1])) for row in rows}


def find_negative_trend(daily_totals: Iterable[Decimal]) -> bool:
    values = [Decimal(str(v)) for v in daily_totals if v is not None]
    if len(values) < 3:
        return False
    # simple monotonic decreasing check across last 3 points
    return values[-1] < values[-2] < values[-3]


def find_potential_overdraft(daily_totals: Iterable[Decimal]) -> bool:
    values = [Decimal(str(v)) for v in daily_totals if v is not None]
    if not values:
        return False
    return any(v < 0 for v in values) or (len(values) >= 2 and values[-1] < 0 and values[-2] <= 0)
