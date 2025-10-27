from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from .utils import trading_days_back


WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def get_sp500_tickers() -> List[str]:
    """Fetch S&P 500 tickers from Wikipedia.

    Returns upper-case ticker symbols compatible with Yahoo Finance.
    """
    tables = pd.read_html(WIKI_SP500_URL)
    # First table contains constituents
    df = tables[0]
    tickers = df["Symbol"].astype(str).str.replace(".", "-", regex=False).str.upper().tolist()
    return tickers


def download_ohlc(
    tickers: List[str], start: datetime, end: Optional[datetime] = None
) -> pd.DataFrame:
    """Download daily OHLC for given tickers.

    Returns a DataFrame with a column MultiIndex: (field, ticker) where field is one of
    ["Open", "High", "Low", "Close", "Adj Close", "Volume"].
    """
    data = yf.download(
        tickers=tickers,
        start=start.strftime("%Y-%m-%d"),
        end=(end.strftime("%Y-%m-%d") if end else None),
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="column",
        threads=True,
    )
    # Ensure column order is (field, ticker)
    if isinstance(data.columns, pd.MultiIndex) and data.columns.nlevels == 2:
        pass
    else:
        # yfinance sometimes returns single ticker with columns as fields only
        data = pd.concat({tickers[0]: data}, axis=1).swaplevel(axis=1)
    data = data.sort_index()
    data.columns = pd.MultiIndex.from_tuples(data.columns, names=["Field", "Ticker"])
    return data


def get_recommendation_buy_percent(ticker: str) -> Optional[float]:
    """Return fraction of Buy recommendations = (strongBuy+buy)/sum counts.

    Returns None if unavailable.
    """
    try:
        tk = yf.Ticker(ticker)
        # yfinance >=0.2.3 provides .recommendations_summary dataframe
        summary = getattr(tk, "recommendations_summary", None)
        if summary is None:
            # some versions provide a method
            getter = getattr(tk, "get_recommendations_summary", None)
            if callable(getter):
                summary = getter()
        if summary is None or len(summary) == 0:
            return None
        # Expect columns: strongBuy, buy, hold, sell, strongSell
        row = summary.iloc[-1]
        strong_buy = int(row.get("strongBuy", 0) or 0)
        buy = int(row.get("buy", 0) or 0)
        hold = int(row.get("hold", 0) or 0)
        sell = int(row.get("sell", 0) or 0)
        strong_sell = int(row.get("strongSell", 0) or 0)
        total = strong_buy + buy + hold + sell + strong_sell
        if total <= 0:
            return None
        return float((strong_buy + buy) / total)
    except Exception:
        return None


def get_many_buy_percents(tickers: List[str]) -> Dict[str, Optional[float]]:
    result: Dict[str, Optional[float]] = {}
    for t in tickers:
        result[t] = get_recommendation_buy_percent(t)
    return result

