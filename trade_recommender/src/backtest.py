from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .data import download_ohlc, get_sp500_tickers, get_many_buy_percents
from .screener import ScreenParameters, screen_universe
from .utils import allocate_evenly, annualized_volatility, trading_days_back
from .options import approximate_intraday_call_return


INDEX_TICKER = "^GSPC"  # S&P 500 index
RISK_FREE_ANNUAL = 0.04


@dataclass
class DailyRecommendation:
    date: pd.Timestamp
    tickers: List[str]


@dataclass
class DailyPerformance:
    date: pd.Timestamp
    stock_return: float
    option_return: float
    combined_return: float
    num_names: int


def run_backtest(
    days: int = 30,
    daily_capital: float = 10_000.0,
    max_names: int = 10,
) -> pd.DataFrame:
    start = trading_days_back(days + 40)
    end = datetime.utcnow()

    # Universe: S&P 500
    tickers = get_sp500_tickers()

    # Pull OHLC for tickers + index
    data = download_ohlc(tickers + [INDEX_TICKER], start=start, end=end)
    index_close = data[("Close", INDEX_TICKER)].dropna()

    # Iterate over the last `days` trading sessions present in data
    common_dates = data.index.intersection(index_close.index)
    if len(common_dates) < days + 11:
        days = max(5, len(common_dates) - 11)
    backtest_dates = common_dates[-days:]

    records: List[DailyPerformance] = []

    for as_of_date in backtest_dates:
        # Slice history up to as_of_date inclusive
        hist = data.loc[:as_of_date]
        if len(hist) < 15:
            continue
        index_hist_close = hist[("Close", INDEX_TICKER)].dropna()

        # Previous trading day (to avoid lookahead)
        if len(hist.index) < 2:
            continue
        prev_date = hist.index[-2]
        hist_prev = data.loc[:prev_date]

        # Prefilter by price action first to reduce API calls for analyst data
        params = ScreenParameters()

        # Compute quick price filters
        prefiltered: List[str] = []
        all_tickers = sorted(set(hist_prev.columns.get_level_values("Ticker")))
        all_tickers = [t for t in all_tickers if t != INDEX_TICKER]
        idx_ret_10 = (hist_prev[("Close", INDEX_TICKER)].pct_change().tail(params.lookback_days) + 1.0).prod() - 1.0
        for t in all_tickers:
            try:
                opens_t = hist_prev[("Open", t)].dropna()
                closes_t = hist_prev[("Close", t)].dropna()
                if len(opens_t) < params.lookback_days + 1 or len(closes_t) < params.lookback_days + 1:
                    continue
                # up days
                up_days = int(((closes_t.tail(params.lookback_days) / opens_t.tail(params.lookback_days)) - 1.0 >= 0).sum())
                if up_days < params.min_up_days:
                    continue
                # relative performance
                stock_ret_10 = (closes_t.pct_change().tail(params.lookback_days) + 1.0).prod() - 1.0
                if idx_ret_10 <= 0:
                    if not (stock_ret_10 > 0 and abs(stock_ret_10) >= params.relative_index_multiplier * abs(idx_ret_10)):
                        continue
                else:
                    if stock_ret_10 < params.relative_index_multiplier * idx_ret_10:
                        continue
                prefiltered.append(t)
            except Exception:
                continue

        # Rank by relative outperformance and keep top 60 to limit API calls
        rel_scores = {}
        for t in prefiltered:
            closes_t = hist_prev[("Close", t)].dropna()
            stock_ret_10 = (closes_t.pct_change().tail(params.lookback_days) + 1.0).prod() - 1.0
            rel_scores[t] = stock_ret_10 - params.relative_index_multiplier * idx_ret_10
        top_prefiltered = [t for t, _ in sorted(rel_scores.items(), key=lambda kv: kv[1], reverse=True)[:60]]

        # Fetch buy fractions only for top candidates
        buy_fracs_subset = get_many_buy_percents(top_prefiltered)

        # Now run full screen using only these buy fractions
        candidates = screen_universe(
            hist_prev.drop(columns=INDEX_TICKER, level=1, errors="ignore"),
            hist_prev[("Close", INDEX_TICKER)].dropna(),
            buy_fracs_subset,
            params,
        )

        # Limit number of names for diversification
        candidates = sorted(candidates, key=lambda r: (r.stock_return_10d - 2.0 * r.index_return_10d), reverse=True)
        selected = candidates[:max_names]
        tickers_today = [r.ticker for r in selected]

        if len(tickers_today) == 0:
            records.append(
                DailyPerformance(
                    date=as_of_date,
                    stock_return=0.0,
                    option_return=0.0,
                    combined_return=0.0,
                    num_names=0,
                )
            )
            continue

        # Compute intraday returns: buy open, sell close
        opens = pd.Series({t: hist[("Open", t)].iloc[-1] for t in tickers_today})
        closes = pd.Series({t: hist[("Close", t)].iloc[-1] for t in tickers_today})
        stock_returns = (closes / opens) - 1.0

        # Estimate vol per name from trailing closes
        vols = {}
        for t in tickers_today:
            vols[t] = max(annualized_volatility(hist[("Close", t)].dropna()), 0.01)

        # Approximate option return for ATM call
        option_returns = {}
        for t in tickers_today:
            option_returns[t] = approximate_intraday_call_return(
                open_price=float(opens[t]),
                close_price=float(closes[t]),
                daily_volatility=float(vols[t]),
                r_annual=RISK_FREE_ANNUAL,
                moneyness=1.0,
                days_to_expiry=30,
            )

        # Allocate half to stocks, half to options by default
        per_bucket = daily_capital / 2.0
        per_name_stock = per_bucket / len(tickers_today)
        per_name_option = per_bucket / len(tickers_today)

        stock_pnl = float((stock_returns * per_name_stock).sum())
        option_pnl = float((pd.Series(option_returns) * per_name_option).sum())
        combined_pnl = stock_pnl + option_pnl

        combined_return = combined_pnl / daily_capital

        rec = DailyPerformance(
            date=as_of_date,
            stock_return=float(stock_pnl / per_bucket) if per_bucket > 0 else 0.0,
            option_return=float(option_pnl / per_bucket) if per_bucket > 0 else 0.0,
            combined_return=combined_return,
            num_names=len(tickers_today),
        )
        # attach attribute for tickers list (for reporting)
        setattr(rec, "tickers", ",".join(tickers_today))
        records.append(rec)

    df = pd.DataFrame([r.__dict__ for r in records]).set_index("date")

    # Benchmark: SPY-like behavior using index intraday open->close
    idx_open = data[("Open", INDEX_TICKER)].reindex(df.index)
    idx_close = data[("Close", INDEX_TICKER)].reindex(df.index)
    idx_ret = (idx_close / idx_open) - 1.0
    df["benchmark_return"] = idx_ret.fillna(0.0)

    df["equity_curve_strategy"] = (1.0 + df["combined_return"]).cumprod()
    df["equity_curve_benchmark"] = (1.0 + df["benchmark_return"]).cumprod()

    # Save a daily recommendations report
    try:
        import os

        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        df_out = df.copy()
        if "tickers" not in df_out.columns:
            df_out["tickers"] = ""
        df_out.to_csv(os.path.join(reports_dir, "daily_recommendations.csv"))
    except Exception:
        pass

    return df


def main():
    df = run_backtest(days=30, daily_capital=10_000.0)
    summary = {
        "strategy_total_return": float(df["equity_curve_strategy"].iloc[-1] - 1.0) if len(df) else 0.0,
        "benchmark_total_return": float(df["equity_curve_benchmark"].iloc[-1] - 1.0) if len(df) else 0.0,
        "avg_daily_return": float(df["combined_return"].mean()) if len(df) else 0.0,
        "win_rate": float((df["combined_return"] > 0).mean()) if len(df) else 0.0,
        "days": int(len(df)),
    }
    print("Backtest Summary:")
    for k, v in summary.items():
        print(f"- {k}: {v:.4f}" if isinstance(v, float) else f"- {k}: {v}")
    print()
    print("Daily Results (head):")
    print(df.head().to_string())


if __name__ == "__main__":
    main()

