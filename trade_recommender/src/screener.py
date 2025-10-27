from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from .utils import count_up_days, cumulative_return


@dataclass
class ScreenParameters:
    lookback_days: int = 10
    min_up_days: int = 8
    min_buy_fraction: float = 0.80
    relative_index_multiplier: float = 2.0


@dataclass
class ScreenResult:
    ticker: str
    up_days: int
    stock_return_10d: float
    index_return_10d: float
    buy_fraction: Optional[float]


def screen_universe(
    ohlc: pd.DataFrame,
    index_close: pd.Series,
    buy_fraction_by_ticker: Dict[str, Optional[float]],
    params: ScreenParameters,
) -> List[ScreenResult]:
    results: List[ScreenResult] = []

    tickers = sorted(set(ohlc.columns.get_level_values("Ticker")))
    for t in tickers:
        try:
            opens = ohlc[("Open", t)].dropna()
            closes = ohlc[("Close", t)].dropna()
            if len(opens) < params.lookback_days + 1 or len(closes) < params.lookback_days + 1:
                continue

            up_days = count_up_days(opens, closes, params.lookback_days)
            stock_ret = cumulative_return(closes, params.lookback_days)
            index_ret = cumulative_return(index_close, params.lookback_days)
            buy_frac = buy_fraction_by_ticker.get(t)

            if up_days < params.min_up_days:
                continue
            if index_ret <= 0:
                # require index_ret positive to avoid division issues; otherwise require stock_ret > 0 and abs(stock_ret) >= 2x abs(index_ret)
                if not (stock_ret > 0 and abs(stock_ret) >= params.relative_index_multiplier * abs(index_ret)):
                    continue
            else:
                if stock_ret < params.relative_index_multiplier * index_ret:
                    continue
            if buy_frac is None or buy_frac < params.min_buy_fraction:
                continue

            results.append(
                ScreenResult(
                    ticker=t,
                    up_days=up_days,
                    stock_return_10d=stock_ret,
                    index_return_10d=index_ret,
                    buy_fraction=buy_frac,
                )
            )
        except Exception:
            continue

    return results

