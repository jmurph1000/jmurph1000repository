# Treasury Dashboard

A simple FastAPI-based dashboard to track daily cash balances (corporate and customer) and security positions. Upload daily spreadsheets (CSV/XLSX) to store historical balances for trend and reporting. The UI highlights negative trends and potential overdrafts.

## Features
- Upload daily cash balances from CSV/XLSX
  - Flexible column mapping; required normalized columns: `as_of_date`, `account_name`, `opening_balance`, optional `account_type`
- Upload security positions from CSV/XLSX
  - Required normalized columns: `as_of_date`, `security_type`, `symbol`, `quantity`, `market_value`, `currency`
- Dashboard shows last 4 days totals for corporate and customer balances with alerts
- Securities summary by type for the latest day, displayed below cash balances
- Trends API for 30-day history
- SQLite storage via SQLAlchemy

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser.

## Spreadsheet formats

### Cash balances
Minimum columns (header names are flexible; they will be normalized):

- `as_of_date`: date (YYYY-MM-DD)
- `account_name`: string (account identifier/name)
- `opening_balance`: number
- `account_type`: optional, one of `corporate` or `customer` (can be provided via form dropdown instead)

Example CSV:

```csv
as_of_date,account_name,opening_balance,account_type
2025-10-06,Operating,1250000,corporate
2025-10-06,Customer Omnibus,980000,customer
2025-10-07,Operating,1245000,corporate
2025-10-07,Customer Omnibus,1005000,customer
```

### Security positions
Required columns:

- `as_of_date`
- `security_type` (e.g., T-Bill, Money Market, Bond)
- `symbol` (optional)
- `quantity` (optional)
- `market_value`
- `currency` (default USD if omitted)

Example CSV:

```csv
as_of_date,security_type,symbol,quantity,market_value,currency
2025-10-07,T-Bill,TBILL-13W,1000000,999500,USD
2025-10-07,Money Market,MMF-ABC,,250000,USD
```

## Notes
- Trend and overdraft alerts are simple heuristics; refine as needed.
- Data stored in `treasury.db` in project root.
- To reset database, delete `treasury.db` and restart.
