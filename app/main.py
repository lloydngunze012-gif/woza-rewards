from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.base import BaseHTTPMiddleware

from sqlalchemy import inspect, text

from app.config import SECRET_KEY
from app.forecast import DEMO_LATE_TAG, build_forecast, due_plus_days, is_demo_late
from app.models import Bill, GraceUse, Payment, Redemption, SessionLocal, User, engine, init_db
from app.seed import (
    CURRENT_PERIOD,
    DEMO_NOW,
    FORECAST_PERIOD,
    REDEMPTION_ORDER,
    REDEMPTION_RATES,
    REDEMPTION_TITLES,
    REDEEM_UNITS_PER_RAND,
    next_tier_info,
    purge_stale_sessions,
    replace_session_user,
    score_label,
    status_for_months,
)

STATIC = Path(__file__).resolve().parent.parent / "static"
SESSION_COOKIE = "woza_session"
SESSION_MAX_AGE = 86400 * 7
API_RATE_LIMIT = "60/minute"
PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_SECRET = SECRET_KEY.encode("utf-8")

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

limiter = Limiter(key_func=get_remote_address, default_limits=[])
app = FastAPI(title="Woza Rewards")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def sign_session(sid: str) -> str:
    digest = hmac.new(_SECRET, sid.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{sid}.{digest}"


def unsigned_session(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    sid, digest = token.rsplit(".", 1)
    if not sid or not digest:
        return None
    expected = hmac.new(_SECRET, sid.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        return None
    return sid


def resolve_period(period: str | None) -> str:
    return period or CURRENT_PERIOD


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
    if "session_key" not in cols:
        statements.append("ALTER TABLE users ADD COLUMN session_key VARCHAR")
    if "created_at" not in cols:
        statements.append("ALTER TABLE users ADD COLUMN created_at DATETIME")
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_session_key ON users (session_key)")
        )


@app.on_event("startup")
def startup():
    migrate_schema()
    db = SessionLocal()
    try:
        purge_stale_sessions(db)
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


def fmt_rand_cents(cents: int) -> str:
    whole = cents // 100
    frac = cents % 100
    whole_s = f"{whole:,}".replace(",", " ")
    if frac == 0:
        return f"R{whole_s}"
    return f"R{whole_s}.{frac:02d}"


def redeem_value_cents(points: int, rate: float) -> int:
    return int(points * rate)


RENT_REDEEM_RATE = REDEMPTION_RATES["rent"]


def worth_up_to_rent_line(points: int) -> str:
    if points <= 0:
        return ""
    cents = redeem_value_cents(points, RENT_REDEEM_RATE)
    return f"worth up to {fmt_rand_cents(cents)} off rent"


def short_points_line(bill: Bill, pay: Payment | None = None) -> str:
    if pay:
        return f"+{fmt_pts_num(pay.points_awarded)} pts"
    if bill.verification == "bank_feed":
        return f"+{fmt_pts_num(bill.points_per_month)} pts when confirmed"
    return f"+{fmt_pts_num(bill.points_per_month)} pts"


def sheet_points_line(points: int) -> str:
    line = f"+{fmt_pts_num(points)} pts"
    worth = worth_up_to_rent_line(points)
    return f"{line} · {worth}" if worth else line


def fmt_rand_from_pts(option: str, points: int) -> str:
    return fmt_rand_cents(redeem_value_cents(points, REDEMPTION_RATES[option]))


def about_units(rands: float, per_rand: float) -> int:
    return int(rands * per_rand)


def redeem_value_row(opt_id: str, points: int) -> str:
    if points <= 0:
        return "Earn points on your bills to unlock"
    cents = redeem_value_cents(points, REDEMPTION_RATES[opt_id])
    display = fmt_rand_cents(cents)
    rands = cents / 100
    units = REDEEM_UNITS_PER_RAND
    if opt_id == "rent":
        return f"{display} off rent"
    if opt_id == "electricity":
        n = about_units(rands, units["electricity"])
        return f"{display} of electricity, about {n} units"
    if opt_id == "data":
        n = about_units(rands, units["data"])
        return f"{display} of data, about {n} GB"
    if opt_id == "fuel":
        n = about_units(rands, units["fuel"])
        return f"{display} of fuel, about {n} litres"
    if opt_id == "groceries":
        return f"{display} at partner stores"
    if opt_id == "ebucks":
        return f"{display} in eBucks"
    if opt_id == "cash":
        return f"{display} to your account"
    return display


def period_add_month(period: str) -> str:
    y, m = map(int, period.split("-"))
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


def period_sub_month(period: str) -> str:
    y, m = map(int, period.split("-"))
    m -= 1
    if m < 1:
        m = 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def periods_ending(end_period: str, count: int) -> list[str]:
    cur = end_period
    out: list[str] = []
    for _ in range(count):
        out.append(cur)
        cur = period_sub_month(cur)
    return list(reversed(out))


MONTH_SHORT = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def period_due_short(period: str) -> str:
    y, m = map(int, period.split("-"))
    return f"1 {MONTH_SHORT[m - 1]}"


def next_unpaid_rent_period(bills: list[Bill]) -> str:
    rent = next((b for b in bills if b.category == "rent"), None)
    if not rent:
        return CURRENT_PERIOD
    period = CURRENT_PERIOD
    for _ in range(36):
        if payment_for_period(rent, period) is None:
            return period
        period = period_add_month(period)
    return period


def woza_cash_rent_subline(bills: list[Bill]) -> str:
    label = period_due_short(next_unpaid_rent_period(bills))
    return f"For your {label} rent"


def rent_woza_cash_apply(
    user: User, bills: list[Bill], period: str = CURRENT_PERIOD
) -> int:
    rent = next((b for b in bills if b.category == "rent"), None)
    if not rent or rent.verification != "through_woza":
        return 0
    if payment_for_period(rent, period):
        return 0
    return min(user.woza_cash_cents, rent.amount_cents)


def woza_cash_amount_lines(amount_cents: int, woza_applied: int) -> dict:
    if woza_applied <= 0:
        return {}
    you_pay_cents = amount_cents - woza_applied
    return {
        "woza_cash_applied_cents": woza_applied,
        "amount_breakdown_line": (
            f"{fmt_rand(amount_cents)} - {fmt_rand_cents(woza_applied)} Woza cash"
        ),
        "you_pay_line": f"You pay {fmt_rand(you_pay_cents)}",
        "you_pay_cents": you_pay_cents,
    }


def demo_now() -> datetime:
    return DEMO_NOW


def session_id_from(request: Request) -> str | None:
    return unsigned_session(request.cookies.get(SESSION_COOKIE))


def user_for_session(db: Session, sid: str | None) -> User | None:
    if not sid:
        return None
    return db.query(User).filter(User.session_key == sid).first()


def set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(sid),
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )


def require_user(request: Request, db: Session) -> User:
    user = user_for_session(db, session_id_from(request))
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


def format_rate_short(rate: float) -> str:
    if rate == 1.0:
        return "1c per point"
    if rate == 1.5:
        return "1.5c per point"
    if rate == 0.5:
        return "0.5c per point"
    return f"{rate}c per point"


def home_bill_badge(
    bill: Bill, period: str = CURRENT_PERIOD, *, bank_consent_active: bool = True
) -> str:
    pay = payment_for_period(bill, period)
    if bill.verification == "bank_feed":
        if not bank_consent_active:
            return "Not verified"
        return ""
    if pay:
        return "Paid"
    return "Due 1 Nov"


def bank_debit_subline(
    bill: Bill, period: str = CURRENT_PERIOD, *, bank_consent_active: bool = True
) -> str | None:
    if bill.verification != "bank_feed" or not bank_consent_active:
        return None
    return "Bank debit order, 1 Nov"


def bill_state(
    bill: Bill,
    period: str = CURRENT_PERIOD,
    *,
    bank_consent_active: bool = True,
    woza_cash_applied_cents: int = 0,
) -> dict:
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
    woza_applied = (
        woza_cash_applied_cents
        if (not pay and woza_cash_applied_cents > 0 and bill.category == "rent")
        else 0
    )
    net_cents = bill.amount_cents - woza_applied
    if bill.verification == "bank_feed":
        status_home = status_pay = "Not verified" if not bank_consent_active else "Debit order 1 Nov"
    elif pay:
        status_home = status_pay = "Paid"
    else:
        status_home = "Due 1 Nov"
        status_pay = "due 1 Nov"
    row_points = short_points_line(bill, pay)
    if woza_applied:
        pay_sheet_detail = (
            f"{bill.name} {fmt_rand(bill.amount_cents)}, "
            f"Woza cash −{fmt_rand_cents(woza_applied)}, "
            f"You pay {fmt_rand(net_cents)}"
        )
    else:
        pay_sheet_detail = f"{bill.name} {fmt_rand(bill.amount_cents)}"
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
        "debit_subline": bank_debit_subline(
            bill, period, bank_consent_active=bank_consent_active
        ),
        "pay_sheet_title": f"Pay {bill.name.lower()} through Woza",
        "row_amount_home": f"{fmt_rand(net_cents)} · {status_home}",
        "row_amount_pay": f"{fmt_rand(net_cents)} · {status_pay}",
        "row_status_home": status_home,
        "row_status_pay": status_pay,
        "row_was_display": fmt_rand(bill.amount_cents) if woza_applied else None,
        "row_now_display": fmt_rand(net_cents) if woza_applied else None,
        "home_points_line": row_points,
        "payment_due_line": f"{fmt_rand(net_cents)} · {status_pay}",
        "pay_sheet_detail": pay_sheet_detail,
        "pay_sheet_points_line": sheet_points_line(pay.points_awarded if pay else potential),
        "pay_sheet_subline": "1 point per rand on time",
        "points_line": row_points,
        "verify_label": verify_label,
        "car_verified": car_verified,
    }
    if pay:
        state["status_line"] = f"+{fmt_pts_num(pay.points_awarded)} pts"
    elif grace:
        state["status_line"] = "Grace month used · no penalty · streak held"
    if woza_applied:
        state.update(woza_cash_amount_lines(bill.amount_cents, woza_applied))
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
    woza_apply_rent = rent_woza_cash_apply(user, bills, period)
    bill_rows = [
        bill_state(
            b,
            period,
            bank_consent_active=user.bank_consent_active,
            woza_cash_applied_cents=woza_apply_rent if b.category == "rent" else 0,
        )
        for b in bills
    ]
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
        months = []
        for month_period in periods_ending(CURRENT_PERIOD, 12):
            y, m = map(int, month_period.split("-"))
            pay = payment_for_period(b, month_period)
            grace = grace_for_period(b, month_period)
            if pay:
                month_status, mark = "paid", "✓"
            elif grace:
                month_status, mark = "grace", "G"
            elif month_period == CURRENT_PERIOD:
                month_status, mark = "due", "·"
            else:
                month_status, mark = "missed", "–"
            months.append(
                {
                    "period": month_period,
                    "label": MONTH_SHORT[m - 1],
                    "year": y,
                    "status": month_status,
                    "mark": mark,
                }
            )
        progress_payments.append(
            {
                "bill_name": b.name,
                "category": b.category,
                "months_on_time": b.months_on_time,
                "months": months,
                "periods": [x["period"] for x in months if x["status"] == "paid"],
            }
        )

    redemption_options = []
    for opt_id in REDEMPTION_ORDER:
        rate = REDEMPTION_RATES[opt_id]
        value_cents = redeem_value_cents(user.points, rate) if user.points > 0 else 0
        value_display = fmt_rand_cents(value_cents) if user.points > 0 else None
        redemption_options.append(
            {
                "id": opt_id,
                "title": REDEMPTION_TITLES[opt_id],
                "rate": format_rate(rate),
                "rate_short": format_rate_short(rate),
                "rate_multiplier": rate,
                "value_cents": value_cents,
                "value_display": value_display,
                "value_row": redeem_value_row(opt_id, user.points),
            }
        )

    tier_max = 48
    mot = user.months_on_time
    months_to_black = max(0, tier_max - mot)
    fill_pct = min(100, int(mot / tier_max * 100))
    tier_ladder = {
        "months": mot,
        "max_months": tier_max,
        "fill_pct": fill_pct,
        "marker_pct": fill_pct,
        "marker_label": f"You: {mot} months",
        "caption_line": f"{months_to_black} months to Black",
        "stops": [
            {"tier": "Silver", "months": 12, "pct": 25, "reached": mot >= 12},
            {"tier": "Gold", "months": 24, "pct": 50, "reached": mot >= 24},
            {"tier": "Black", "months": 48, "pct": 100, "reached": mot >= 48},
        ],
    }

    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "status": status,
            "months_on_time": user.months_on_time,
            "score": 742,
            "score_label": score_label(742),
            "score_caption": "Not a credit score",
            "initials": initials_for(user.name),
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
            "woza_cash_display": fmt_rand_cents(user.woza_cash_cents),
            "woza_cash_subline": woza_cash_rent_subline(bills),
            "grace_months": user.grace_months,
            "grace_months_earned": user.grace_months_earned,
            "grace_months_used": grace_used,
            "member_since": "Oct 2023",
            "tier_progress": tier,
            "next_tier": tier.get("next") or "Black",
            "months_to_next_tier": tier.get("months_needed", months_to_black),
        },
        "meta": {
            "current_period": period,
            "due_display": "1 Nov 2026",
            "demo_now": demo_now().isoformat(),
        },
        "home": {
            "months_to_black_line": f"{months_to_black} months to Black",
            "tier_ladder": tier_ladder,
            "bureau_line": "36 on-time months shared with the credit bureau",
            "bills_on_track": ["Rent", "Utilities", "Car finance"],
        },
        "payments": {
            "hero_title": "Due through Woza" if payable_outstanding else "Paid through Woza",
            "hero_amount": fmt_rand(due_woza_cents if payable_outstanding else paid_woza_cents),
            "hero_amount_suffix": "" if payable_outstanding else " ✓",
            "hero_you_pay_line": (
                f"You pay {fmt_rand(due_woza_cents - woza_apply_rent)}"
                if payable_outstanding
                else ""
            ),
            "hero_bills_line": (
                (
                    f"{fmt_rand(due_woza_cents)} in bills · "
                    f"{fmt_rand_cents(woza_apply_rent)} Woza cash applied"
                    if woza_apply_rent
                    else f"{fmt_rand(due_woza_cents)} in bills"
                )
                if payable_outstanding
                else ""
            ),
            **(
                woza_cash_amount_lines(due_woza_cents, woza_apply_rent)
                if payable_outstanding and woza_apply_rent > 0
                else {}
            ),
            "hero_earn_line": (
                f"Earns {fmt_pts_num(due_woza_pts)} pts"
                if payable_outstanding and due_woza_pts
                else ""
            ),
            "hero_grace_line": f"{user.grace_months} grace months available ({user.grace_months_earned} earned, {grace_used} used)",
            "all_woza_paid": all_woza_paid,
            "payable_outstanding": payable_outstanding,
            "bills": bill_rows,
        },
        "rewards": {
            "redemption_options": redemption_options,
            "redeem_units_per_rand": REDEEM_UNITS_PER_RAND,
            "redemptions": [
                {
                    "option": r.option,
                    "points_spent": r.points_spent,
                    "value_display": fmt_rand_cents(r.value_cents),
                    "created_at": r.created_at.isoformat(),
                }
                for r in redemptions
            ],
            "benefits": {
                "grace_months": user.grace_months,
                "grace_months_earned": user.grace_months_earned,
                "grace_months_used": grace_used,
                "tier": status,
                "gold_unlocks": [
                    "2 grace months available (3 earned, 1 used)",
                    "Your on-time record, ready to share with lenders",
                    "Rent and utilities shared with the credit bureau",
                ],
                "black_unlocks": [
                    f"{months_to_black} more on-time months for Black tier",
                    "Priority access to partner offers",
                    "Priority support and exclusive offers",
                ],
                "next_tier": tier.get("next") or "Black",
                "months_to_next_tier": months_to_black,
                "bureau": {
                    "rent_months": 36,
                    "utilities_months": 36,
                    "car_note": "Car already on file; on-time only",
                },
            },
            "progress": progress_payments,
            "progress_timeline_label": "Last 12 months",
        },
        "bureau_summary": bureau_summary(user, db),
    }


def bills_for_forecast(user: User, db: Session) -> list[Bill]:
    return (
        db.query(Bill)
        .filter(Bill.user_id == user.id)
        .options(joinedload(Bill.payments), joinedload(Bill.grace_uses))
        .all()
    )


def forecast_payload(user: User, db: Session) -> dict:
    return build_forecast(user, bills_for_forecast(user, db), target_period=FORECAST_PERIOD)


def bureau_summary(user: User, db: Session) -> dict:
    bills = db.query(Bill).filter(Bill.user_id == user.id).all()
    monthly = sum(b.amount_cents for b in bills)
    membership = status_for_months(user.months_on_time)
    months_to_black = max(0, 48 - user.months_on_time)
    return {
        "on_time_months": user.months_on_time,
        "bill_count": len(bills),
        "monthly_display": fmt_rand(monthly),
        "status": membership,
        "membership_tier": membership,
        "tier_progress_months": user.months_on_time,
        "months_to_black": months_to_black,
        "tier_goal_line": f"{months_to_black} months to Black"
        if months_to_black
        else "Black tier reached",
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
    user.lifetime_points += pts
    user.points += pts
    if bill.category == "rent" and user.woza_cash_cents > 0:
        applied = min(user.woza_cash_cents, bill.amount_cents)
        user.woza_cash_cents -= applied
    db.flush()
    return pay


class LoginBody(ApiModel):
    phone: str = ""
    name: str = ""


class ResetBody(ApiModel):
    name: str = ""


def format_member_name(raw: str) -> str:
    parts = [p for p in (raw or "").split() if p]
    if not parts:
        return ""
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def initials_for(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "W"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def apply_member_name(user: User, raw: str) -> None:
    name = format_member_name(raw)
    if name:
        user.name = name


class EmptyBody(ApiModel):
    pass


class PayBody(ApiModel):
    bill_id: int = Field(..., ge=1)
    period: str | None = Field(default=None, pattern=PERIOD_PATTERN)
    amount_cents: int | None = Field(default=None, gt=0)


class PayAllBody(ApiModel):
    period: str | None = Field(default=None, pattern=PERIOD_PATTERN)
    amount_cents: int | None = Field(default=None, gt=0)


class GraceBody(ApiModel):
    bill_id: int = Field(..., ge=1)
    period: str | None = Field(default=None, pattern=PERIOD_PATTERN)
    amount_cents: int | None = Field(default=None, gt=0)


class RedeemBody(ApiModel):
    option: str
    points: int = Field(..., gt=0)
    amount_cents: int | None = Field(default=None, gt=0)


@app.post("/api/login")
@limiter.limit(API_RATE_LIMIT)
def login(request: Request, body: LoginBody, response: Response, db: DbDep):
    name = format_member_name(body.name)
    if not name:
        raise HTTPException(400, "Enter your name")
    sid = session_id_from(request) or secrets.token_urlsafe(32)
    existing = user_for_session(db, sid)
    user = replace_session_user(db, session_key=sid, name=name, existing=existing)
    set_session_cookie(response, sid)
    return {"ok": True, "name": user.name}


@app.post("/api/logout")
@limiter.limit(API_RATE_LIMIT)
def logout(request: Request, response: Response, body: EmptyBody = EmptyBody()):
    response.delete_cookie(SESSION_COOKIE, samesite="lax")
    return {"ok": True}


@app.get("/api/me")
@limiter.limit(API_RATE_LIMIT)
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
@limiter.limit(API_RATE_LIMIT)
def pay_bill_endpoint(request: Request, body: PayBody, db: DbDep):
    user = require_user(request, db)
    bill = db.query(Bill).filter(Bill.id == body.bill_id, Bill.user_id == user.id).first()
    if not bill:
        raise HTTPException(404, "Bill not found")
    payment = pay_bill(user, db, bill, resolve_period(body.period))
    db.commit()
    db.refresh(user)
    payload = build_me_payload(user, db)
    payload["event"] = {
        "kind": "payment",
        "title": f"{bill.name} paid",
        "points_added": payment.points_awarded,
        "points_line": f"+{fmt_pts_num(payment.points_awarded)} points",
        "worth_rent_line": worth_up_to_rent_line(payment.points_awarded),
        "new_balance": user.points,
        "new_balance_line": f"New balance: {fmt_pts_num(user.points)} pts",
        "bill_name": bill.name,
    }
    return payload


@app.post("/api/pay_all")
@limiter.limit(API_RATE_LIMIT)
def pay_all(request: Request, db: DbDep, body: PayAllBody = PayAllBody()):
    user = require_user(request, db)
    period = resolve_period(body.period)
    bills = (
        db.query(Bill)
        .filter(Bill.user_id == user.id)
        .options(joinedload(Bill.payments), joinedload(Bill.grace_uses))
        .all()
    )
    for bill in bills:
        if bill.verification != "through_woza":
            continue
        if not payment_for_period(bill, period) and not grace_for_period(bill, period):
            pay_bill(user, db, bill, period)
    db.commit()
    db.refresh(user)
    return build_me_payload(user, db)


@app.post("/api/grace")
@limiter.limit(API_RATE_LIMIT)
def use_grace(request: Request, body: GraceBody, db: DbDep):
    raise HTTPException(400, "Grace months apply automatically when a payment is late")


@app.post("/api/redeem")
@limiter.limit(API_RATE_LIMIT)
def redeem(request: Request, body: RedeemBody, db: DbDep):
    user = require_user(request, db)
    if body.option not in REDEMPTION_RATES:
        raise HTTPException(400, "Invalid option")
    if body.points > user.points:
        raise HTTPException(400, "Insufficient points")
    rate = REDEMPTION_RATES[body.option]
    value_cents = redeem_value_cents(body.points, rate)
    user.points -= body.points
    user.redeemed_points += body.points
    if body.option in ("cash", "rent"):
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
    bills = db.query(Bill).filter(Bill.user_id == user.id).options(joinedload(Bill.payments)).all()
    rent_period = next_unpaid_rent_period(bills)
    rent_label = period_due_short(rent_period)
    value_display = fmt_rand_cents(value_cents)
    payload = build_me_payload(user, db)
    event = {
        "kind": "redeem",
        "option": body.option,
        "points_spent": body.points,
        "value_cents": value_cents,
        "value_display": value_display,
    }
    if body.option == "rent":
        event["success_message"] = (
            f"{value_display} added to Woza cash for your {rent_label} rent"
        )
    payload["event"] = event
    return payload


@app.post("/api/revoke_bank_consent")
@limiter.limit(API_RATE_LIMIT)
def revoke_bank_consent(request: Request, db: DbDep, body: EmptyBody = EmptyBody()):
    user = require_user(request, db)
    user.bank_consent_active = False
    db.commit()
    db.refresh(user)
    return build_me_payload(user, db)


@app.post("/api/reset")
@limiter.limit(API_RATE_LIMIT)
def reset_demo(request: Request, response: Response, db: DbDep, body: ResetBody = ResetBody()):
    user = require_user(request, db)
    sid = user.session_key or session_id_from(request) or secrets.token_urlsafe(32)
    name = format_member_name(body.name) or user.name
    user = replace_session_user(db, session_key=sid, name=name, existing=user)
    set_session_cookie(response, sid)
    return build_me_payload(user, db)


@app.get("/api/lender_view")
@limiter.limit(API_RATE_LIMIT)
def lender_view(request: Request, db: DbDep):
    user = require_user(request, db)
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
            "membership_tier": after["membership_tier"],
            "months_to_black": after["months_to_black"],
            "tier_goal_line": after["tier_goal_line"],
            "summary": (
                f"{after['on_time_months']} on-time months, {after['bill_count']} bills, "
                f"{after['monthly_display']}/month, {after['membership_tier']}, "
                f"score {after['score']}, {after['grace_unused']} grace unused"
            ),
        },
        "predicted_affordability": forecast_payload(user, db)["predicted_affordability"],
    }


@app.get("/api/forecast")
@limiter.limit(API_RATE_LIMIT)
def forecast(request: Request, db: DbDep):
    user = require_user(request, db)
    return forecast_payload(user, db)


class SimulateLateBody(ApiModel):
    bill_id: int = Field(..., ge=1)


@app.post("/api/demo/simulate_late")
@limiter.limit(API_RATE_LIMIT)
def simulate_late(request: Request, body: SimulateLateBody, db: DbDep):
    user = require_user(request, db)
    bill = (
        db.query(Bill)
        .filter(Bill.id == body.bill_id, Bill.user_id == user.id)
        .options(joinedload(Bill.payments), joinedload(Bill.grace_uses))
        .first()
    )
    if not bill:
        raise HTTPException(404, "Bill not found")
    period = FORECAST_PERIOD
    existing = payment_for_period(bill, period)
    if existing and is_demo_late(existing.verified_by):
        return forecast_payload(user, db)
    if grace_for_period(bill, period) and existing is None:
        raise HTTPException(400, "Grace month already used")
    late_at = due_plus_days(period, bill.due_day, 14)
    if existing:
        original = existing.verified_by or bill.verification
        existing.on_time = False
        existing.points_awarded = 0
        existing.paid_at = late_at
        existing.verified_by = f"{DEMO_LATE_TAG}:{original}"
    else:
        db.add(
            Payment(
                bill_id=bill.id,
                period=period,
                paid_at=late_at,
                on_time=False,
                verified_by=DEMO_LATE_TAG,
                points_awarded=0,
            )
        )
    db.commit()
    db.expire_all()
    return forecast_payload(user, db)


@app.post("/api/demo/undo_late")
@limiter.limit(API_RATE_LIMIT)
def undo_late(request: Request, db: DbDep, body: EmptyBody = EmptyBody()):
    user = require_user(request, db)
    bills = bills_for_forecast(user, db)
    changed = False
    for bill in bills:
        for pay in list(bill.payments or []):
            if not is_demo_late(pay.verified_by):
                continue
            changed = True
            tag = pay.verified_by or DEMO_LATE_TAG
            if ":" in tag:
                original = tag.split(":", 1)[1]
                y, m = map(int, pay.period.split("-"))
                pay.on_time = True
                pay.points_awarded = bill.points_per_month
                pay.paid_at = datetime(y, m, 1, 10, 0, 0)
                pay.verified_by = original
            else:
                db.delete(pay)
    if changed:
        db.commit()
        db.expire_all()
    return forecast_payload(user, db)


@app.get("/api/health")
@limiter.limit(API_RATE_LIMIT)
def health(request: Request):
    return {"ok": True, "service": "woza-rewards"}


NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
OG_CACHE = {"Cache-Control": "public, max-age=604800"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


@app.get("/card-preview")
def card_preview_page():
    return FileResponse(STATIC / "card-preview.html", headers=NO_CACHE)


@app.get("/static/og.jpg")
def og_image():
    path = STATIC / "og.jpg"
    if not path.is_file():
        raise HTTPException(404, "Preview image not found")
    return FileResponse(path, media_type="image/jpeg", headers=OG_CACHE)


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
