from __future__ import annotations

from datetime import date, timedelta, datetime
from decimal import Decimal
from typing import Any
import os
import smtplib
from email.message import EmailMessage
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
import json
from sqlalchemy import select, text
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
from .models import Invite, User
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
    # Gate access: allow if a User exists and is_accepted for this session's email (simplified demo: via query ?email=...)
    # In production, use proper auth with sessions. Here, we support invite acceptance link with token.
    email = request.query_params.get("email")
    if email:
        user = db.scalar(select(User).where(User.email == email))
        if not user or not user.is_accepted:
            return HTMLResponse("Access pending. Check your email invite.", status_code=403)
    else:
        return HTMLResponse("Email required. Append ?email=you@example.com", status_code=401)
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

    corp_has_negative = any(x < 0 for x in corporate_totals)
    cust_has_negative = any(x < 0 for x in customer_totals)
    corp_state = "negative" if corp_has_negative else ("trending" if neg_trend_corp else "normal")
    cust_state = "negative" if cust_has_negative else ("trending" if neg_trend_cust else "normal")

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "email": email,
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
            "corp_state": corp_state,
            "cust_state": cust_state,
        },
    )


@app.post("/upload/cash")
async def upload_cash(
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    account_type_hint: str | None = Form(None),
    email: str | None = Form(None),
) -> dict[str, Any]:
    if email:
        user = db.scalar(select(User).where(User.email == email))
        if not user or not user.is_accepted:
            raise HTTPException(status_code=403, detail="Access pending or denied")
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
    email: str | None = Form(None),
) -> dict[str, Any]:
    if email:
        user = db.scalar(select(User).where(User.email == email))
        if not user or not user.is_accepted:
            raise HTTPException(status_code=403, detail="Access pending or denied")
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


def _generate_token() -> str:
    import secrets

    return secrets.token_urlsafe(24)


def _send_invite_email(recipient: str, token: str) -> None:
    base_url = os.environ.get("BASE_URL", "http://localhost:8000")
    accept_url = f"{base_url}/accept?token={token}"
    sender = os.environ.get("EMAIL_FROM", os.environ.get("SMTP_USER", "no-reply@example.com"))
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not host or not user or not password:
        # SMTP not configured; skip sending
        return
    msg = EmailMessage()
    msg["Subject"] = "You're invited to Treasury Dashboard"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(f"You have been invited to access the Treasury Dashboard. Click to accept: {accept_url}")
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)


@app.post("/invite")
async def invite_user(email: str = Form(...), inviter: str = Form(...), db: Session = Depends(get_db)) -> Any:
    # Only allow specific inviter email per request
    if inviter.lower() != "john.murphy@gusto.com":
        raise HTTPException(status_code=403, detail="Only the owner can invite users")

    # Upsert user (inactive until accepted)
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, is_active=True, is_accepted=False)
        db.add(user)
        db.flush()

    # Create invite token
    token = _generate_token()
    invite = Invite(email=email, token=token, invited_by_email=inviter, created_at=datetime.utcnow())
    db.add(invite)
    db.commit()

    # Attempt to send email (optional if SMTP configured); always return acceptance URL
    try:
        _send_invite_email(email, token)
    except Exception:
        pass
    base_url = os.environ.get("BASE_URL", "")
    accept_url = (base_url + "/accept?token=" + token) if base_url else ("/accept?token=" + token)
    return {"status": "ok", "accept_url": accept_url}


@app.get("/accept")
async def accept_invite(token: str, db: Session = Depends(get_db)) -> Any:
    invite = db.scalar(select(Invite).where(Invite.token == token, Invite.is_used == False))
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or used token")
    user = db.scalar(select(User).where(User.email == invite.email))
    if not user:
        user = User(email=invite.email, is_active=True, is_accepted=True, accepted_at=datetime.utcnow())
        db.add(user)
    else:
        user.is_accepted = True
        user.accepted_at = datetime.utcnow()
    invite.is_used = True
    db.commit()
    # Redirect to dashboard with email parameter
    return RedirectResponse(url=f"/?email={user.email}", status_code=302)


@app.on_event("startup")
async def on_startup() -> None:
    # Nothing to initialize yet; tables are created at import time.
    return None
