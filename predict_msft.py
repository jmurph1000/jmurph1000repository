#!/usr/bin/env python3
"""
MSFT (Microsoft) next-day direction predictor

This script downloads recent MSFT OHLCV data, engineers simple features,
trains a quick model, and outputs an UP/DOWN prediction for the next day.

Notes
- Educational only. Not investment advice.
- Uses yfinance for data. Internet required.
- Keeps code explicit and readable. Not optimized for performance.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd


def _lazy_imports():
    # Import heavy deps only when needed
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime import
        raise SystemExit(
            "Missing dependency 'yfinance'. Run: pip install -r requirements.txt"
        ) from exc

    try:
        from sklearn.ensemble import RandomForestClassifier  # type: ignore
        from sklearn.metrics import accuracy_score  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime import
        raise SystemExit(
            "Missing dependency 'scikit-learn'. Run: pip install -r requirements.txt"
        ) from exc

    return yf, RandomForestClassifier, accuracy_score


@dataclass
class TrainResult:
    model: object
    features_last_row: pd.DataFrame
    columns: list[str]
    train_accuracy: Optional[float]
    n_train: int


def fetch_msft_history(period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    yf, _, _ = _lazy_imports()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download("MSFT", period=period, interval=interval, auto_adjust=True, progress=False)
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise SystemExit("Failed to download MSFT data. Check internet connection.")
    df = df.rename(columns=str.lower)
    df = df.reset_index()
    return df


def engineer_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    # Expect columns: Date, open, high, low, close, volume
    data = df.copy()
    data = data.sort_values("Date")
    data["return_1d"] = data["close"].pct_change()
    data["return_5d"] = data["close"].pct_change(5)
    data["vol_chg_5d"] = data["volume"].pct_change(5)
    data["high_low_spread"] = (data["high"] - data["low"]) / data["close"]
    data["close_open"] = (data["close"] - data["open"]) / data["open"]

    # Simple technical indicators
    data["sma_5"] = data["close"].rolling(5).mean()
    data["sma_10"] = data["close"].rolling(10).mean()
    data["sma_ratio_5_10"] = data["sma_5"] / data["sma_10"]
    data["rsi_14"] = _compute_rsi(data["close"], window=14)

    # Target: next-day direction (1 if next close > today close)
    data["target"] = (data["close"].shift(-1) > data["close"]).astype(int)

    # Drop rows with NaNs from rolling features
    data = data.dropna().reset_index(drop=True)

    feature_cols = [
        "return_1d",
        "return_5d",
        "vol_chg_5d",
        "high_low_spread",
        "close_open",
        "sma_ratio_5_10",
        "rsi_14",
    ]
    X = data[feature_cols]
    y = data["target"]
    return X, y


def _compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def train_model(X: pd.DataFrame, y: pd.Series, n_estimators: int = 200, random_state: int = 42) -> TrainResult:
    _, RandomForestClassifier, accuracy_score = _lazy_imports()
    if len(X) < 100:
        raise SystemExit("Not enough data after feature engineering. Try longer period.")

    # Simple chronological split to avoid leakage
    split_index = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_index], X.iloc[split_index:]
    y_train, y_test = y.iloc[:split_index], y.iloc[split_index:]

    model = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=None,
        min_samples_leaf=2,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    train_accuracy: Optional[float] = None
    if len(X_test) > 0:
        y_pred = model.predict(X_test)
        train_accuracy = float(accuracy_score(y_test, y_pred))

    features_last_row = X.iloc[[-1]]
    return TrainResult(
        model=model,
        features_last_row=features_last_row,
        columns=list(X.columns),
        train_accuracy=train_accuracy,
        n_train=len(X_train),
    )


def predict_next_day_direction(result: TrainResult) -> Tuple[str, float]:
    proba = None
    try:
        proba = result.model.predict_proba(result.features_last_row)[0][1]
    except Exception:
        # Fallback if model has no predict_proba
        pred = int(result.model.predict(result.features_last_row)[0])
        proba = 0.5 if pred == 1 else 0.5
    direction = "UP" if proba >= 0.5 else "DOWN"
    confidence = float(abs(proba - 0.5) * 2)
    return direction, confidence


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Predict MSFT next-day direction (educational)")
    parser.add_argument("--period", default="2y", help="History period for yfinance (e.g., 1y, 2y, 5y)")
    parser.add_argument("--interval", default="1d", help="Data interval (e.g., 1d, 1h)")
    parser.add_argument("--n-estimators", type=int, default=200, help="RandomForest trees")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--print-features", action="store_true", help="Print last feature row")
    args = parser.parse_args(argv)

    df = fetch_msft_history(period=args.period, interval=args.interval)
    X, y = engineer_features(df)
    result = train_model(X, y, n_estimators=args.n_estimators, random_state=args.seed)
    direction, confidence = predict_next_day_direction(result)

    print(f"Prediction: {direction}")
    print(f"Confidence: {confidence:.2f}")
    if result.train_accuracy is not None:
        print(f"Backtest accuracy (holdout): {result.train_accuracy:.3f} on {result.n_train} train obs")
    if args.print_features:
        with pd.option_context("display.max_columns", None, "display.width", 120):
            print("Last feature row:")
            print(result.features_last_row)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

