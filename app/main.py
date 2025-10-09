from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
import json
from sqlalchemy import text
from sqlalchemy.orm import Session

from .crud import (
    find_negative_trend,
    find_potential_overdraft,
    get_cash_totals_by_type_for_dates,
    get_security_summary_by_type_for_date,
    upsert_daily_balances_from_records,
    upsert_security_positions_from_records,
)
from .db import Base, SessionLocal, engine
from .utils import (
    normalize_cash_records,
    normalize_securities_records,
    read_spreadsheet_to_records,
)

app = FastAPI(title="Treasury Dashboard")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


# Create tables
Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/healthz")
def health() -> dict[str, str]:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)) -> Any:
    today = date.today()
    days = [today - timedelta(days=i) for i in range(0, 4)]
    days.sort()

    cash_series = get_cash_totals_by_type_for_dates(db, days)
    corporate_totals = [Decimal(str(x["corporate_total"])) for x in cash_series]
    customer_totals = [Decimal(str(x["customer_total"])) for x in cash_series]

    neg_trend_corp = find_negative_trend(corporate_totals)
    overdraft_corp = find_potential_overdraft(corporate_totals)
    neg_trend_cust = find_negative_trend(customer_totals)
    overdraft_cust = find_potential_overdraft(customer_totals)

    security_summary_today = get_security_summary_by_type_for_date(db, days[-1])

    labels = [d.isoformat() for d in days]
    corp_data = [float(x) for x in corporate_totals]
    cust_data = [float(x) for x in customer_totals]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "days": days,
            "cash_series": cash_series,
            "corporate_totals": corporate_totals,
            "customer_totals": customer_totals,
            "neg_trend_corp": neg_trend_corp,
            "overdraft_corp": overdraft_corp,
            "neg_trend_cust": neg_trend_cust,
            "overdraft_cust": overdraft_cust,
            "security_summary_today": security_summary_today,
            "labels_json": json.dumps(labels),
            "corp_data_json": json.dumps(corp_data),
            "cust_data_json": json.dumps(cust_data),
        },
    )


@app.post("/upload/cash")
async def upload_cash(
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    account_type_hint: str | None = Form(None),
) -> dict[str, Any]:
    content = await file.read()
    try:
        records = read_spreadsheet_to_records(content, file.filename)
        records = normalize_cash_records(records)
        upserted = upsert_daily_balances_from_records(db, records, account_type_hint=account_type_hint)
        return {"status": "ok", "upserted": upserted}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/upload/securities")
async def upload_securities(
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    content = await file.read()
    try:
        records = read_spreadsheet_to_records(content, file.filename)
        records = normalize_securities_records(records)
        upserted = upsert_security_positions_from_records(db, records)
        return {"status": "ok", "upserted": upserted}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/trends/cash")
async def trends_cash(db: Session = Depends(get_db)) -> Any:
    today = date.today()
    days = [today - timedelta(days=i) for i in range(0, 30)]
    days.sort()
    series = get_cash_totals_by_type_for_dates(db, days)
    return {"days": [d.isoformat() for d in days], "series": series}


@app.on_event("startup")
async def on_startup() -> None:
    # Nothing to initialize yet; tables are created at import time.
    return None
