from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class AccountBase(BaseModel):
    name: str
    account_type: str
    institution: Optional[str] = None
    account_number: Optional[str] = None
    currency: str = "USD"
    is_active: bool = True


class AccountCreate(AccountBase):
    pass


class AccountRead(AccountBase):
    id: int

    class Config:
        from_attributes = True


class DailyBalanceBase(BaseModel):
    as_of_date: date
    opening_balance: Decimal


class DailyBalanceCreate(DailyBalanceBase):
    account_id: int


class DailyBalanceRead(DailyBalanceBase):
    id: int
    account_id: int

    class Config:
        from_attributes = True


class SecurityPositionBase(BaseModel):
    as_of_date: date
    security_type: str
    symbol: Optional[str] = None
    quantity: Optional[Decimal] = None
    market_value: Decimal
    currency: str = "USD"


class SecurityPositionCreate(SecurityPositionBase):
    pass


class SecurityPositionRead(SecurityPositionBase):
    id: int

    class Config:
        from_attributes = True


class BalanceTrendPoint(BaseModel):
    as_of_date: date
    corporate_total: Decimal
    customer_total: Decimal


class SecuritySummaryPoint(BaseModel):
    as_of_date: date
    totals_by_type: dict[str, Decimal]


class InviteCreate(BaseModel):
    email: str


class InviteRead(BaseModel):
    email: str
    token: str


class UserRead(BaseModel):
    email: str
    is_active: bool
    is_accepted: bool
