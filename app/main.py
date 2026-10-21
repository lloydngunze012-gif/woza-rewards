from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.models import Bill, GraceUse, Payment, Redemption, SessionLocal, User, init_db
from app.seed import (
    CURRENT_PERIOD,
    DEMO_NOW,
    PAYDAY,
    REDEMPTION_RATES,
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


@app.on_event("startup")
def startup():
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def fmt_pts(n: int) -> str:
    s = f"{n:,}".replace(",", " ")
    return f"{s} pts"


def fmt_rand(cents: int) -> str:
    rands = cents // 100
    s = f"{rands:,}".replace(",", " ")
    return f"R{s}"


def demo_now() -> datetime:
    return DEMO_NOW


def points_multiplier(at: datetime | None = None) -> int:
    at = at or demo_now()
    if at < PAYDAY:
        return 2
    return 1


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


def bill_state(bill: Bill, period: str = CURRENT_PERIOD) -> dict:
    pay = payment_for_period(bill, period)
    grace = grace_for_period(bill, period)
    mult = points_multiplier()
    potential = bill.points_per_month * mult
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
        "is_auto": bill.verification == "bank_feed",
    }
    if pay:
        state["status_line"] = f"Paid · {fmt_pts(pay.points_awarded)} earned"
    elif grace:
        state["status_line"] = "Grace month used · no penalty · streak held"
    return state


def all_bills_paid(user: User, db: Session, period: str) -> bool:
    bills = db.query(Bill).filter(Bill.user_id == user.id).all()
    for b in bills:
        if payment_for_period(b, period) is None and grace_for_period(b, period) is None:
            return False
    return True


def month_earned_points(user: User, db: Session, period: str) -> int:
    total = 0
    bills = db.query(Bill).filter(Bill.user_id == user.id).all()
    for b in bills:
        p = payment_for_period(b, period)
        if p:
            total += p.points_awarded
    return total


def build_me_payload(user: User, db: Session) -> dict:
    bills = (
        db.query(Bill)
        .filter(Bill.user_id == user.id)
        .options(joinedload(Bill.payments), joinedload(Bill.grace_uses))
        .all()
    )
    period = CURRENT_PERIOD
    bill_rows = [bill_state(b, period) for b in bills]
    total_due = sum(b.amount_cents for b in bills if not bill_state(b, period)["paid"])
    total_potential = sum(
        bill_state(b, period)["potential_points"]
        for b in bills
        if not bill_state(b, period)["paid"]
    )
    tier = next_tier_info(user.months_on_time)
    status = status_for_months(user.months_on_time)
    earned_month = month_earned_points(user, db, period)

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

    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "status": status,
            "months_on_time": user.months_on_time,
            "score": user.score,
            "score_label": score_label(user.score),
            "points": user.points,
            "points_display": fmt_pts(user.points),
            "lifetime_points": user.lifetime_points,
            "lifetime_display": fmt_pts(user.lifetime_points),
            "woza_cash_cents": user.woza_cash_cents,
            "woza_cash_display": fmt_rand(user.woza_cash_cents),
            "grace_months": user.grace_months,
            "tier_progress": tier,
        },
        "meta": {
            "current_period": period,
            "due_display": "1 Nov 2026",
            "payday_display": "25 Oct 2026",
            "payday_multiplier": points_multiplier(),
            "demo_now": demo_now().isoformat(),
        },
        "home": {
            "greeting": f"Good morning, {user.name.split()[0]}",
            "month_earned_points": earned_month,
            "month_earned_display": fmt_pts(earned_month),
            "month_potential_points": 9_200,
            "status_line": f"{status} · {user.months_on_time} months  →  {tier['next'] or 'Top tier'} in {tier['months_needed']} months"
            if tier["next"]
            else f"{status} · {user.months_on_time} months",
            "progress_label": f"{tier['progress_num']} / {tier['progress_den']} months to {tier['next'] or 'Black'}",
            "bills_on_track": ["Rent", "Utilities", "Car"],
        },
        "payments": {
            "total_due_cents": total_due,
            "total_due_display": fmt_rand(total_due),
            "earn_if_paid_display": fmt_pts(total_potential if total_potential else 9_200),
            "bills": bill_rows,
        },
        "rewards": {
            "redemption_options": [
                {
                    "id": "rent",
                    "title": "Towards Next Rent",
                    "rate": "1.5 cents per point",
                    "example": "100 000 pts = R1 500",
                },
                {
                    "id": "ebucks",
                    "title": "eBucks",
                    "rate": "1 cent per point",
                    "example": "100 000 pts = R1 000",
                },
                {
                    "id": "airtime",
                    "title": "Airtime",
                    "rate": "1 cent per point",
                    "example": "100 000 pts = R1 000",
                },
                {
                    "id": "cash",
                    "title": "Cash Out to Bank",
                    "rate": "0.5 cents per point",
                    "example": "100 000 pts = R500",
                },
            ],
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
                "tier": status,
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
        "on_time_months": user.months_on_time,
        "bill_count": len(bills),
        "monthly_display": fmt_rand(monthly),
        "status": status_for_months(user.months_on_time),
        "score": user.score,
        "grace_unused": user.grace_months,
    }


def pay_bill(user: User, db: Session, bill: Bill, period: str = CURRENT_PERIOD) -> Payment:
    if payment_for_period(bill, period):
        raise HTTPException(400, "Already paid for this period")
    if grace_for_period(bill, period):
        raise HTTPException(400, "Grace month already used")

    at = demo_now()
    mult = points_multiplier(at)
    pts = bill.points_per_month * mult
    verified = bill.verification

    pay = Payment(
        bill_id=bill.id,
        period=period,
        paid_at=at,
        on_time=True,
        verified_by=verified,
        points_awarded=pts,
    )
    db.add(pay)
    bill.months_on_time += 1
    user.points += pts
    user.lifetime_points += pts

    if user.demo_payments_count < 18 and user.score < 760:
        user.score += 1
        user.demo_payments_count += 1

    user.status = status_for_months(user.months_on_time)

    db.flush()
    if all_bills_paid(user, db, period):
        user.months_on_time += 1
        user.status = status_for_months(user.months_on_time)
        earned = user.months_on_time // 12
        if earned > (user.months_on_time - 1) // 12:
            pass
        prev_grace_earned = max(0, (user.months_on_time - 1) // 12 - 2)
        new_grace_earned = max(0, user.months_on_time // 12 - 2)
        if new_grace_earned > prev_grace_earned:
            user.grace_months += new_grace_earned - prev_grace_earned

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
    pay_bill(user, db, bill)
    db.commit()
    db.refresh(user)
    return build_me_payload(user, db)


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
        if not payment_for_period(bill, CURRENT_PERIOD) and not grace_for_period(
            bill, CURRENT_PERIOD
        ):
            pay_bill(user, db, bill)
    db.commit()
    db.refresh(user)
    return build_me_payload(user, db)


@app.post("/api/grace")
def use_grace(body: GraceBody, request: Request, db: DbDep):
    user = require_user(request, db)
    if user.grace_months <= 0:
        raise HTTPException(400, "No grace months available")
    bill = db.query(Bill).filter(Bill.id == body.bill_id, Bill.user_id == user.id).first()
    if not bill:
        raise HTTPException(404, "Bill not found")
    if payment_for_period(bill, CURRENT_PERIOD):
        raise HTTPException(400, "Bill already paid")
    if grace_for_period(bill, CURRENT_PERIOD):
        raise HTTPException(400, "Grace already used")
    db.add(
        GraceUse(
            bill_id=bill.id,
            period=CURRENT_PERIOD,
            used_at=demo_now(),
        )
    )
    user.grace_months -= 1
    db.commit()
    db.refresh(user)
    return build_me_payload(user, db)


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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/lender")
def lender_page():
    return FileResponse(STATIC / "lender.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
