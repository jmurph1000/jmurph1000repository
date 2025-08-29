from __future__ import annotations

import csv
import io
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import urllib.request


INDEX_TICKER = "IWM"


def to_stooq_symbol(ticker: str) -> str:
    # Map US tickers to stooq .us symbols; keep indices/etfs as lowercase with .us
    t = ticker.lower()
    if t.endswith(".us"):
        return t
    # Handle class tickers like BRK-B -> brk-b.us
    t = t.replace(".", "-")
    return f"{t}.us"


def fetch_iwm_holdings(limit: int = 120) -> List[str]:
    url = (
        "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/"
        "1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
    )
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read().decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(data))
        tickers: List[str] = []
        for row in reader:
            sym = row.get("Ticker") or row.get("Ticker Symbol") or row.get("Ticker\xa0")
            if not sym:
                continue
            s = sym.strip().upper().replace(".", "-")
            if s and s.isascii():
                tickers.append(s)
            if len(tickers) >= limit:
                break
    except Exception:
        tickers = []
    # Fallback small-cap sample if parsing failed
    if len(tickers) < 5:
        tickers = [
            "RGEN","GME","BYND","FIVE","SMCI","PI","CROX","ENPH","CAR","TXRH",
            "OLED","APPF","AVAV","FSLR","CELH","ALGM","RXO","BLKB","RUN","KNSL",
        ][:limit]
    return tickers


def utc_now_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def days_ago_str(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def fetch_stooq_csv(ticker: str) -> List[Dict[str, str]]:
    sym = to_stooq_symbol(ticker)
    domains = ["stooq.com", "stooq.pl"]
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv"}
    last_err: Optional[Exception] = None
    for attempt in range(6):
        domain = domains[attempt % len(domains)]
        url = f"https://{domain}/q/d/l/?s={sym}&i=d"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = resp.read().decode("utf-8", errors="ignore")
            rows: List[Dict[str, str]] = []
            reader = csv.DictReader(io.StringIO(data))
            for row in reader:
                rows.append(row)
            if rows:
                return rows
        except Exception as e:
            last_err = e
            import time
            time.sleep(0.7 * (attempt + 1))
            continue
    if last_err:
        raise last_err
    return []


def pct_change(a: float, b: float) -> float:
    if a == 0:
        return 0.0
    return (b / a) - 1.0


def rolling_up_days(rows: List[Dict[str, str]], lookback: int) -> int:
    tail = rows[-lookback:]
    up = 0
    for r in tail:
        try:
            o = float(r["Open"]) if r["Open"] != "null" else float(r["Adj Close"])
            c = float(r["Close"]) if r["Close"] != "null" else float(r["Adj Close"])
        except Exception:
            continue
        if c >= o:
            up += 1
    return up


def cumulative_return_close(rows: List[Dict[str, str]], lookback: int) -> float:
    tail = rows[-lookback:]
    prod = 1.0
    prev = None
    for r in tail:
        try:
            c = float(r["Adj Close"]) if r["Adj Close"] != "null" else float(r["Close"]) 
        except Exception:
            continue
        if prev is None:
            prev = c
            continue
        prod *= (c / prev)
        prev = c
    return prod - 1.0 if prod != 1.0 else 0.0


def intraday_return(rows: List[Dict[str, str]]) -> float:
    r = rows[-1]
    try:
        o = float(r["Open"]) if r["Open"] != "null" else float(r["Adj Close"]) 
        c = float(r["Close"]) if r["Close"] != "null" else float(r["Adj Close"]) 
    except Exception:
        return 0.0
    if o == 0:
        return 0.0
    return (c / o) - 1.0


def estimate_option_intraday_return(stock_open: float, stock_close: float) -> float:
    # Simple convexity proxy: scale stock return by a factor depending on magnitude
    r = (stock_close / stock_open) - 1.0 if stock_open > 0 else 0.0
    # Assume ATM call with leverage ~ delta/gamma; simplistic: 2.5x for small moves, capped
    factor = 2.5
    return max(min(r * factor, 1.5), -0.95)


UNIVERSE: List[str] = []


def get_buy_fraction_placeholder(ticker: str) -> Optional[float]:
    # Disabled for small caps in stdlib mode
    return None


def backtest(days: int = 30, daily_capital: float = 10_000.0, enforce_buy_filter: bool = False) -> Tuple[List[Tuple[str, List[str]]], List[Tuple[str,float,float,float,int]]]:
    # Fetch index (IWM via Stooq)
    idx_rows = fetch_stooq_csv(INDEX_TICKER)
    idx_by_date = {r["Date"]: r for r in idx_rows if r.get("Close") not in (None, "null")}
    dates = sorted(idx_by_date.keys())
    if len(dates) < days + 11:
        days = max(5, len(dates) - 11)
    backtest_dates = dates[-days:]

    per_day_recos: List[Tuple[str, List[str]]] = []
    per_day_perf: List[Tuple[str, float, float, float, int]] = []

    # Universe from IWM holdings
    global UNIVERSE
    UNIVERSE = fetch_iwm_holdings(limit=120)

    # Preload historical rows per ticker
    hist_cache: Dict[str, List[Dict[str, str]]] = {}
    import time
    for t in UNIVERSE:
        try:
            hist_cache[t] = fetch_stooq_csv(t)
        except Exception:
            hist_cache[t] = []
        time.sleep(0.35)

    for d in backtest_dates:
        # previous day cutoff to avoid lookahead
        prev_dates = [x for x in dates if x < d]
        if len(prev_dates) < 11:
            continue
        prev_cutoff = prev_dates[-1]

        # screen
        idx_hist_for_screen = [r for r in idx_rows if r["Date"] <= prev_cutoff]
        idx_ret10 = cumulative_return_close(idx_hist_for_screen, 10)

        candidates: List[Tuple[str, float]] = []
        for t in UNIVERSE:
            rows = [r for r in hist_cache.get(t, []) if r.get("Date")]
            rows = [r for r in rows if r["Date"] <= prev_cutoff]
            if len(rows) < 11:
                continue
            up = rolling_up_days(rows, 10)
            if up < 8:
                continue
            sret10 = cumulative_return_close(rows, 10)
            if (idx_ret10 > 0 and sret10 < 2.0 * idx_ret10) or (idx_ret10 <= 0 and not (sret10 > 0 and abs(sret10) >= 2.0 * abs(idx_ret10))):
                continue
            if enforce_buy_filter:
                buyf = get_buy_fraction_placeholder(t)
                if buyf is None or buyf < 0.80:
                    continue
            score = sret10 - 2.0 * idx_ret10
            candidates.append((t, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        tickers_today = [t for t, _ in candidates[:10]]
        per_day_recos.append((d, tickers_today))

        # performance on day d (stocks only)
        stock_pnl = 0.0
        if len(tickers_today) > 0:
            per_name_stock = daily_capital / len(tickers_today)
            for t in tickers_today:
                # find row for d
                rows_full = [r for r in hist_cache.get(t, []) if r.get("Date") == d]
                if not rows_full:
                    continue
                r = rows_full[0]
                try:
                    o = float(r["Open"]) if r["Open"] != "null" else float(r["Adj Close"]) 
                    c = float(r["Close"]) if r["Close"] != "null" else float(r["Adj Close"]) 
                except Exception:
                    continue
                if o <= 0:
                    continue
                sr = (c / o) - 1.0
                stock_pnl += per_name_stock * sr
        combined = stock_pnl
        num = len(tickers_today)
        per_day_perf.append((d, stock_pnl / (daily_capital) if num else 0.0, 0.0, combined / daily_capital if num else 0.0, num))

    return per_day_recos, per_day_perf


def main():
    recos, perf = backtest(days=30, daily_capital=10_000.0)
    eq_strat = 1.0
    eq_bench = 1.0

    # benchmark from index open->close
    idx_rows = fetch_stooq_csv(INDEX_TICKER)
    idx_by_date = {r["Date"]: r for r in idx_rows}

    print("Daily Recommendations and Performance (stocks only):")
    for (d, names), (_, stock_r, _, comb_r, n) in zip(recos, perf):
        # benchmark for day d
        r = idx_by_date.get(d)
        if r:
            try:
                o = float(r["Open"]) if r["Open"] != "null" else float(r["Adj Close"]) 
                c = float(r["Close"]) if r["Close"] != "null" else float(r["Adj Close"]) 
                bench_r = (c / o) - 1.0 if o else 0.0
            except Exception:
                bench_r = 0.0
        else:
            bench_r = 0.0
        eq_strat *= (1.0 + comb_r)
        eq_bench *= (1.0 + bench_r)
        print(f"{d}: names={names} | stock={stock_r:.4f} comb={comb_r:.4f} bench={bench_r:.4f}")

    print()
    print(f"Strategy total return: {eq_strat-1.0:.4f}")
    print(f"Benchmark total return: {eq_bench-1.0:.4f}")


if __name__ == "__main__":
    main()

