from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from sqlalchemy import inspect, text

from app.models import Bill, GraceUse, Payment, Redemption, SessionLocal, User, engine, init_db
from app.seed import (
    CURRENT_PERIOD,
    DEMO_NOW,
    REDEMPTION_RATES,
    REDEEM_VALUE_LABELS,
    drop_and_reseed,
    next_tier_info,
    score_label,
    seed_if_empty,
    status_for_months,
)

STATIC = Path(__file__).resolve().parent.parent / "static"
SESSION_COOKIE = "woza_session"
_sessions: dict[str, int] = {}

app = FastAPI(title="Woza Rewards")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbDep = Annotated[Session, Depends(get_db)]


def migrate_schema() -> None:
    init_db()
    insp = inspect(engine)
    if not insp.has_table("users"):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    statements = []
    if "redeemed_points" not in cols:
        statements.append("ALTER TABLE users ADD COLUMN redeemed_points INTEGER DEFAULT 0")
    if "grace_months_earned" not in cols:
        statements.append("ALTER TABLE users ADD COLUMN grace_months_earned INTEGER DEFAULT 0")
    if "demo_version" not in cols:
        statements.append("ALTER TABLE users ADD COLUMN demo_version INTEGER DEFAULT 0")
    if "bank_consent_active" not in cols:
        statements.append("ALTER TABLE users ADD COLUMN bank_consent_active BOOLEAN DEFAULT 1")
    if statements:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))


@app.on_event("startup")
def startup():
    migrate_schema()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def fmt_pts(n: int) -> str:
    s = f"{n:,}".replace(",", " ")
    return f"{s} pts"


def fmt_pts_num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def fmt_rand(cents: int) -> str:
    rands = cents // 100
    s = f"{rands:,}".replace(",", " ")
    return f"R{s}"


def fmt_rand_from_pts(option: str, points: int) -> str:
    rate = REDEMPTION_RATES[option]
    cents = int(points * rate)
    rands = cents / 100
    if rands == int(rands):
        return f"R{int(rands):,}".replace(",", " ")
    return f"R{rands:,.2f}".replace(",", " ")


def demo_now() -> datetime:
    return DEMO_NOW


def get_user_id(request: Request) -> int | None:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    return _sessions.get(sid)


def require_user(request: Request, db: Session) -> User:
    uid = get_user_id(request)
    if not uid:
        raise HTTPException(401, "Not logged in")
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(401, "Not logged in")
    return user


def payment_for_period(bill: Bill, period: str) -> Payment | None:
    for p in bill.payments:
        if p.period == period:
            return p
    return None


def grace_for_period(bill: Bill, period: str) -> GraceUse | None:
    for g in bill.grace_uses:
        if g.period == period:
            return g
    return None


def month_activity_line(bill: Bill, period: str = CURRENT_PERIOD) -> str:
    pay = payment_for_period(bill, period)
    if pay:
        return f"+{fmt_pts_num(pay.points_awarded)} pts"
    if bill.verification == "bank_feed":
        return f"+{fmt_pts_num(bill.points_per_month)} pts once your bank confirms it"
    return f"Due 1 Nov · earns {fmt_pts_num(bill.points_per_month)} pts"


def format_rate(rate: float) -> str:
    if rate == 1.0:
        return "1 cent per point"
    if rate == 1.5:
        return "1.5 cents per point"
    if rate == 0.5:
        return "0.5 cents per point"
    return f"{rate} cents per point"


def home_points_line(bill: Bill) -> str:
    pts = fmt_pts_num(bill.points_per_month)
    if bill.verification == "bank_feed":
        return f"+{pts} pts when your bank confirms"
    return f"+{pts} pts"


def home_bill_badge(
    bill: Bill, period: str = CURRENT_PERIOD, *, bank_consent_active: bool = True
) -> str:
    pay = payment_for_period(bill, period)
    if bill.verification == "bank_feed":
        if not bank_consent_active:
            return "Not verified"
        return "Bank debit order, 1 Nov"
    if pay:
        return "Paid"
    return "Due 1 Nov"


def bill_state(bill: Bill, period: str = CURRENT_PERIOD, *, bank_consent_active: bool = True) -> dict:
    pay = payment_for_period(bill, period)
    grace = grace_for_period(bill, period)
    potential = bill.points_per_month
    is_woza = bill.verification == "through_woza"
    car_verified = bank_consent_active and bill.verification == "bank_feed"
    if bill.verification == "bank_feed" and not bank_consent_active:
        verify_label = "Not verified"
    elif bill.verification == "bank_feed":
        verify_label = "Verified: Debit order read"
    else:
        verify_label = "Verified: Paid through Woza"
    points_line = home_points_line(bill)
    if pay:
        points_line = f"+{fmt_pts_num(pay.points_awarded)} pts"
    state = {
        "id": bill.id,
        "name": bill.name,
        "category": bill.category,
        "amount_cents": bill.amount_cents,
        "amount_display": fmt_rand(bill.amount_cents),
        "payee": bill.payee,
        "verification": bill.verification,
        "due_day": bill.due_day,
        "months_on_time": bill.months_on_time,
        "points_per_month": bill.points_per_month,
        "paid": pay is not None,
        "grace_used": grace is not None,
        "points_awarded": pay.points_awarded if pay else 0,
        "potential_points": potential,
        "potential_display": fmt_pts(potential),
        "is_bank_debit": bill.verification == "bank_feed",
        "payable_through_woza": is_woza and pay is None and grace is None,
        "month_line": month_activity_line(bill, period),
        "home_badge": home_bill_badge(bill, period, bank_consent_active=bank_consent_active),
        "pay_sheet_title": f"Pay {fmt_rand(bill.amount_cents)} {bill.name.lower()} through Woza",
        "home_points_line": home_points_line(bill),
        "payment_due_line": f"{fmt_rand(bill.amount_cents)} · due 1 Nov",
        "points_line": points_line,
        "verify_label": verify_label,
        "car_verified": car_verified,
    }
    if pay:
        state["status_line"] = f"+{fmt_pts_num(pay.points_awarded)} pts"
    elif grace:
        state["status_line"] = "Grace month used · no penalty · streak held"
    return state


def all_bills_paid(user: User, db: Session, period: str) -> bool:
    bills = db.query(Bill).filter(Bill.user_id == user.id).all()
    for b in bills:
        if payment_for_period(b, period) is None and grace_for_period(b, period) is None:
            return False
    return True


def build_me_payload(user: User, db: Session) -> dict:
    bills = (
        db.query(Bill)
        .filter(Bill.user_id == user.id)
        .options(joinedload(Bill.payments), joinedload(Bill.grace_uses))
        .all()
    )
    period = CURRENT_PERIOD
    bill_rows = [bill_state(b, period, bank_consent_active=user.bank_consent_active) for b in bills]
    tier = next_tier_info(user.months_on_time)
    status = status_for_months(user.months_on_time)
    grace_used = db.query(GraceUse).join(Bill).filter(Bill.user_id == user.id).count()

    woza_bills = [b for b in bills if b.verification == "through_woza"]
    paid_woza_cents = sum(
        b.amount_cents
        for b in woza_bills
        if payment_for_period(b, period) is not None
    )
    due_woza_cents = sum(
        b.amount_cents for b in woza_bills if payment_for_period(b, period) is None
    )
    due_woza_pts = sum(
        b.points_per_month for b in woza_bills if payment_for_period(b, period) is None
    )
    payable_outstanding = any(b["payable_through_woza"] for b in bill_rows)
    all_woza_paid = due_woza_cents == 0 and paid_woza_cents > 0

    redemptions = (
        db.query(Redemption)
        .filter(Redemption.user_id == user.id)
        .order_by(Redemption.created_at.desc())
        .limit(20)
        .all()
    )

    progress_payments = []
    for b in bills:
        periods = sorted({p.period for p in b.payments})
        progress_payments.append(
            {
                "bill_name": b.name,
                "months_on_time": b.months_on_time,
                "periods": periods[-12:],
            }
        )

    redemption_options = []
    for opt_id, rate in REDEMPTION_RATES.items():
        titles = {
            "rent": "Towards next rent",
            "ebucks": "eBucks",
            "airtime": "Airtime",
            "cash": "Cash out to bank",
        }
        examples = {
            "rent": "100 000 pts = R1 500",
            "ebucks": "100 000 pts = R1 000",
            "airtime": "100 000 pts = R1 000",
            "cash": "100 000 pts = R500",
        }
        val = fmt_rand_from_pts(opt_id, user.points)
        suffix = REDEEM_VALUE_LABELS[opt_id]
        redemption_options.append(
            {
                "id": opt_id,
                "title": titles[opt_id],
                "rate": format_rate(rate),
                "example": examples[opt_id],
                "your_value_line": f"Your {fmt_pts_num(user.points)} pts = {val} {suffix}",
            }
        )

    months_to_gold = max(0, 24 - user.months_on_time) if user.months_on_time < 24 else 0
    gold_progress_label = f"{user.months_on_time} of 24 on-time months"
    gold_progress_pct = min(100, int(user.months_on_time / 24 * 100)) if user.months_on_time < 24 else 100

    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "status": status,
            "months_on_time": user.months_on_time,
            "score": 742,
            "score_label": score_label(742),
            "score_caption": "Not your credit bureau score",
            "initials": "TM",
            "linked_bank": {
                "label": "FNB Cheque ••4821",
                "consent_until": "Consent active until Oct 2027",
                "consent_active": user.bank_consent_active,
            },
            "available_points": user.points,
            "available_display": fmt_pts(user.points),
            "redeemed_points": user.redeemed_points,
            "redeemed_display": fmt_pts(user.redeemed_points),
            "lifetime_points": user.lifetime_points,
            "lifetime_display": fmt_pts(user.lifetime_points),
            "woza_cash_cents": user.woza_cash_cents,
            "woza_cash_display": fmt_rand(user.woza_cash_cents),
            "woza_cash_subline": "From redeemed points - applied to your next Woza bill",
            "grace_months": user.grace_months,
            "grace_months_earned": user.grace_months_earned,
            "grace_months_used": grace_used,
            "member_since": "Oct 2023",
            "tier_progress": tier,
        },
        "meta": {
            "current_period": period,
            "due_display": "1 Nov 2026",
            "demo_now": demo_now().isoformat(),
        },
        "home": {
            "greeting": f"Good morning, {user.name.split()[0]}",
            "months_to_gold_line": f"{months_to_gold} months to Gold",
            "gold_progress_label": gold_progress_label,
            "gold_progress_pct": gold_progress_pct,
            "bureau_line": "36 on-time months shared with the credit bureau",
            "bills_on_track": ["Rent", "Utilities", "Car finance"],
        },
        "payments": {
            "hero_title": "Due through Woza" if payable_outstanding else "Paid through Woza",
            "hero_amount": fmt_rand(due_woza_cents if payable_outstanding else paid_woza_cents),
            "hero_amount_suffix": "" if payable_outstanding else " ✓",
            "hero_earn_line": f"Earns {fmt_pts_num(due_woza_pts)} pts" if payable_outstanding else "",
            "hero_grace_line": f"{user.grace_months} grace months available ({user.grace_months_earned} earned, {grace_used} used)",
            "all_woza_paid": all_woza_paid,
            "payable_outstanding": payable_outstanding,
            "bills": bill_rows,
        },
        "rewards": {
            "redemption_options": redemption_options,
            "redemptions": [
                {
                    "option": r.option,
                    "points_spent": r.points_spent,
                    "value_display": fmt_rand(r.value_cents),
                    "created_at": r.created_at.isoformat(),
                }
                for r in redemptions
            ],
            "benefits": {
                "grace_months": user.grace_months,
                "grace_months_earned": user.grace_months_earned,
                "grace_months_used": grace_used,
                "tier": status,
                "silver_unlocks": [
                    "2 grace months available (3 earned, 1 used)",
                    "Silver rate at partner lenders",
                    "Rent and utilities reported to the bureau",
                ],
                "gold_unlocks": [
                    "24 on-time months for Gold tier",
                    "Better partner lender rates",
                    "Higher redemption value on rent",
                ],
                "bureau": {
                    "rent_months": 36,
                    "utilities_months": 30,
                    "car_note": "Car already on file; on-time only",
                },
            },
            "progress": progress_payments,
        },
        "bureau_summary": bureau_summary(user, db),
    }


def bureau_summary(user: User, db: Session) -> dict:
    bills = db.query(Bill).filter(Bill.user_id == user.id).all()
    monthly = sum(b.amount_cents for b in bills)
    return {
        "on_time_months": 36,
        "bill_count": len(bills),
        "monthly_display": fmt_rand(monthly),
        "status": status_for_months(user.months_on_time),
        "score": 742,
        "grace_unused": user.grace_months,
    }


def pay_bill(user: User, db: Session, bill: Bill, period: str = CURRENT_PERIOD) -> Payment:
    if bill.verification != "through_woza":
        raise HTTPException(400, "This bill is paid via bank debit order")
    if payment_for_period(bill, period):
        raise HTTPException(400, "Already paid for this period")
    if grace_for_period(bill, period):
        raise HTTPException(400, "Grace month already used")

    at = demo_now()
    pts = bill.points_per_month
    pay = Payment(
        bill_id=bill.id,
        period=period,
        paid_at=at,
        on_time=True,
        verified_by=bill.verification,
        points_awarded=pts,
    )
    db.add(pay)
    bill.months_on_time += 1
    user.lifetime_points += pts
    user.points += pts

    user.status = status_for_months(user.months_on_time)
    db.flush()
    if all_bills_paid(user, db, period):
        user.months_on_time += 1
        user.status = status_for_months(user.months_on_time)

    return pay


class LoginBody(BaseModel):
    phone: str = ""


class PayBody(BaseModel):
    bill_id: int


class GraceBody(BaseModel):
    bill_id: int


class RedeemBody(BaseModel):
    option: str
    points: int


@app.post("/api/login")
def login(body: LoginBody, response: Response, db: DbDep):
    user = db.query(User).first()
    if not user:
        drop_and_reseed()
        db.expire_all()
        user = db.query(User).first()
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = user.id
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
    )
    return {"ok": True, "name": user.name}


@app.get("/api/me")
def me(request: Request, db: DbDep):
    user = require_user(request, db)
    user = (
        db.query(User)
        .filter(User.id == user.id)
        .options(
            joinedload(User.bills).joinedload(Bill.payments),
            joinedload(User.bills).joinedload(Bill.grace_uses),
        )
        .first()
    )
    return build_me_payload(user, db)


@app.post("/api/pay")
def pay_bill_endpoint(body: PayBody, request: Request, db: DbDep):
    user = require_user(request, db)
    bill = db.query(Bill).filter(Bill.id == body.bill_id, Bill.user_id == user.id).first()
    if not bill:
        raise HTTPException(404, "Bill not found")
    payment = pay_bill(user, db, bill)
    db.commit()
    db.refresh(user)
    payload = build_me_payload(user, db)
    payload["event"] = {
        "kind": "payment",
        "points_added": payment.points_awarded,
        "bill_name": bill.name,
    }
    return payload


@app.post("/api/pay_all")
def pay_all(request: Request, db: DbDep):
    user = require_user(request, db)
    bills = (
        db.query(Bill)
        .filter(Bill.user_id == user.id)
        .options(joinedload(Bill.payments), joinedload(Bill.grace_uses))
        .all()
    )
    for bill in bills:
        if bill.verification != "through_woza":
            continue
        if not payment_for_period(bill, CURRENT_PERIOD) and not grace_for_period(
            bill, CURRENT_PERIOD
        ):
            pay_bill(user, db, bill)
    db.commit()
    db.refresh(user)
    return build_me_payload(user, db)


@app.post("/api/grace")
def use_grace(body: GraceBody, request: Request, db: DbDep):
    raise HTTPException(400, "Grace months apply automatically when a payment is late")


@app.post("/api/redeem")
def redeem(body: RedeemBody, request: Request, db: DbDep):
    user = require_user(request, db)
    if body.option not in REDEMPTION_RATES:
        raise HTTPException(400, "Invalid option")
    if body.points <= 0:
        raise HTTPException(400, "Invalid points")
    if body.points > user.points:
        raise HTTPException(400, "Insufficient points")
    rate = REDEMPTION_RATES[body.option]
    value_cents = int(body.points * rate)
    user.points -= body.points
    user.redeemed_points += body.points
    if body.option == "cash":
        user.woza_cash_cents += value_cents
    db.add(
        Redemption(
            user_id=user.id,
            option=body.option,
            points_spent=body.points,
            value_cents=value_cents,
            created_at=demo_now(),
        )
    )
    db.commit()
    db.refresh(user)
    payload = build_me_payload(user, db)
    payload["event"] = {
        "kind": "redeem",
        "option": body.option,
        "points_spent": body.points,
        "value_display": fmt_rand(value_cents),
    }
    return payload


@app.post("/api/revoke_bank_consent")
def revoke_bank_consent(request: Request, db: DbDep):
    user = require_user(request, db)
    user.bank_consent_active = False
    db.commit()
    db.refresh(user)
    return build_me_payload(user, db)


@app.post("/api/reset")
def reset_demo(request: Request, response: Response, db: DbDep):
    get_user_id(request)
    drop_and_reseed()
    db.expire_all()
    user = db.query(User).first()
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = user.id
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
    )
    return build_me_payload(user, db)


@app.get("/api/lender_view")
def lender_view(db: DbDep):
    user = db.query(User).first()
    if not user:
        return {"before": {}, "after": {}}
    after = bureau_summary(user, db)
    return {
        "before": {
            "headline": "Before Woza",
            "points": [
                "No bureau file for rent or utilities",
                "No cross-institution payment record",
            ],
        },
        "after": {
            "headline": "With Woza",
            "on_time_months": after["on_time_months"],
            "bill_count": after["bill_count"],
            "monthly_display": after["monthly_display"],
            "status": after["status"],
            "score": after["score"],
            "grace_unused": after["grace_unused"],
            "summary": f"{after['on_time_months']} on-time months, {after['bill_count']} bills, {after['monthly_display']}/month, {after['status']}, score {after['score']}, {after['grace_unused']} grace unused",
        },
    }


@app.get("/api/health")
def health():
    return {"ok": True, "service": "woza-rewards"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/lender")
def lender_page():
    return FileResponse(STATIC / "lender.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
