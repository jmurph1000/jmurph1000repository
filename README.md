# MSFT Direction Predictor (Educational)

This small script downloads recent Microsoft (MSFT) price data, engineers a few features, trains a quick model, and prints an UP or DOWN guess for the next day, along with a simple confidence score.

> Educational use only. Not investment advice.

## Quickstart

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python predict_msft.py --help
```

Example run:

```bash
python predict_msft.py --period 2y --interval 1d --print-features
```

Sample output:

```
Prediction: UP
Confidence: 0.61
Backtest accuracy (holdout): 0.54 on 400 train obs
```

## How it works
- Downloads MSFT OHLCV with `yfinance`.
- Engineers simple features (returns, moving averages, RSI, spreads).
- Trains a `RandomForestClassifier` with a chronological train/holdout split.
- Predicts next-day direction using the latest feature row.

## Notes
- Internet is required to download data.
- Feature set and model are intentionally simple; results vary.
- For reproducibility, set `--seed`.
- You can change history with `--period` (e.g., `1y`, `2y`, `5y`).

## Disclaimer
This repository and script are provided for educational purposes only and do not constitute financial advice. Use at your own risk.