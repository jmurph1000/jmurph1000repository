import math
from datetime import datetime, timedelta
from typing import Iterable, List

import numpy as np
import pandas as pd


def trading_days_back(num_days: int) -> datetime:
    """Return a start date sufficiently far back to capture num_days trading sessions.

    We overshoot by ~2x calendar days to handle weekends/holidays.
    """
    return datetime.utcnow() - timedelta(days=int(num_days * 2.2) + 5)


def percent_change(series: pd.Series) -> pd.Series:
    """Simple percentage change helper, drops NaNs."""
    return series.pct_change().replace([np.inf, -np.inf], np.nan).dropna()


def count_up_days(opens: pd.Series, closes: pd.Series, lookback: int = 10) -> int:
    """Count number of up days in the last `lookback` sessions using open->close return >= 0."""
    returns = (closes.tail(lookback) / opens.tail(lookback)) - 1.0
    return int((returns >= 0).sum())


def cumulative_return(prices: pd.Series, lookback: int) -> float:
    """Cumulative simple return over last `lookback` bars (close-to-close)."""
    pct = prices.pct_change().tail(lookback)
    pct = pct.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    total = float((1.0 + pct).prod() - 1.0)
    return total


def annualized_volatility(prices: pd.Series, trading_days: int = 252) -> float:
    """Estimate annualized volatility from daily close prices."""
    r = prices.pct_change().dropna()
    return float(r.std(ddof=0) * math.sqrt(trading_days))


def allocate_evenly(total_capital: float, num_assets: int) -> List[float]:
    if num_assets <= 0:
        return []
    per = total_capital / float(num_assets)
    return [per for _ in range(num_assets)]

