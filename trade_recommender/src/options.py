import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass
class BSParams:
    underlying_price: float
    strike_price: float
    time_to_expiry_years: float
    risk_free_rate: float
    volatility: float


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_call(params: BSParams) -> float:
    S = max(params.underlying_price, 1e-12)
    K = max(params.strike_price, 1e-12)
    T = max(params.time_to_expiry_years, 1e-8)
    r = params.risk_free_rate
    sigma = max(params.volatility, 1e-8)

    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    call = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return float(max(call, 0.0))


def approximate_intraday_call_return(
    open_price: float,
    close_price: float,
    daily_volatility: float,
    r_annual: float,
    moneyness: float = 1.0,
    days_to_expiry: int = 30,
) -> float:
    """Approximate ATM call return for an intraday move from open to close.

    We treat the option as an ATM call with fixed days_to_expiry, and compute BS price
    at open (S0) and at close (S1). We use the same implied vol equal to daily_volatility
    annualized (input expected to be annualized already).
    Returns simple return: (C1 - C0) / C0
    """
    if daily_volatility <= 0:
        return 0.0

    T = max(days_to_expiry / 252.0, 1e-8)
    K_open = open_price * moneyness
    K_close = close_price * moneyness

    p0 = black_scholes_call(
        BSParams(
            underlying_price=open_price,
            strike_price=K_open,
            time_to_expiry_years=T,
            risk_free_rate=r_annual,
            volatility=daily_volatility,
        )
    )
    p1 = black_scholes_call(
        BSParams(
            underlying_price=close_price,
            strike_price=K_close,
            time_to_expiry_years=max(T - 1 / 252.0, 1e-8),
            risk_free_rate=r_annual,
            volatility=daily_volatility,
        )
    )
    if p0 <= 0:
        return 0.0
    return float((p1 - p0) / p0)

