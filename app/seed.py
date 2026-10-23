from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Bill, GraceUse, Payment, Redemption, User, engine

DEMO_NOW = datetime(2026, 10, 21, 9, 0, 0)
# Payments, Home due-copy, and Forecast what-if all use November 2026 so
# "due 1 Nov" and "simulate a missed car payment" mark the same period.
CURRENT_PERIOD = "2026-11"
FORECAST_PERIOD = CURRENT_PERIOD
DEMO_VERSION = 7

AVAILABLE_POINTS = 12_000
LIFETIME_POINTS = 331_200
REDEEMED_POINTS = 319_200


def _periods_back(end_period: str, count: int) -> list[str]:
    y, m = map(int, end_period.split("-"))
    out: list[str] = []
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


SESSION_TTL_DAYS = 7
DEFAULT_MEMBER_NAME = "Thandi Mokoena"


def drop_and_reseed() -> None:
    from app.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def delete_user_data(db: Session, user: User) -> None:
    bills = db.query(Bill).filter(Bill.user_id == user.id).all()
    bill_ids = [b.id for b in bills]
    if bill_ids:
        db.query(Payment).filter(Payment.bill_id.in_(bill_ids)).delete(synchronize_session=False)
        db.query(GraceUse).filter(GraceUse.bill_id.in_(bill_ids)).delete(synchronize_session=False)
        db.query(Bill).filter(Bill.id.in_(bill_ids)).delete(synchronize_session=False)
    db.query(Redemption).filter(Redemption.user_id == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.flush()


def purge_stale_sessions(db: Session, *, days: int = SESSION_TTL_DAYS) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    stale = []
    for user in db.query(User).all():
        if not user.session_key:
            stale.append(user)
            continue
        created = user.created_at
        if created is None or created < cutoff:
            stale.append(user)
    for user in stale:
        delete_user_data(db, user)
    if stale:
        db.commit()
    return len(stale)


def seed_demo_user(db: Session, *, name: str, session_key: str) -> User:
    user = _seed(db, name=name or DEFAULT_MEMBER_NAME, session_key=session_key)
    db.commit()
    db.refresh(user)
    return user


def replace_session_user(
    db: Session, *, session_key: str, name: str, existing: User | None = None
) -> User:
    if existing is not None:
        delete_user_data(db, existing)
    return seed_demo_user(db, name=name, session_key=session_key)


def _seed(db: Session, name: str = DEFAULT_MEMBER_NAME, session_key: str | None = None) -> User:
    user = User(
        name=name,
        phone="072 418 3390",
        status="Gold",
        months_on_time=36,
        score=742,
        points=AVAILABLE_POINTS,
        lifetime_points=LIFETIME_POINTS,
        redeemed_points=REDEEMED_POINTS,
        woza_cash_cents=12_500,
        grace_months=2,
        grace_months_earned=3,
        demo_version=DEMO_VERSION,
        bank_consent_active=True,
        session_key=session_key,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()

    db.add(
        Redemption(
            user_id=user.id,
            option="rent",
            points_spent=REDEEMED_POINTS,
            value_cents=int(REDEEMED_POINTS * 1.5),
            created_at=datetime(2026, 9, 15, 12, 0, 0),
        )
    )

    bills_spec = [
        {
            "name": "Rent",
            "category": "rent",
            "amount_cents": 450_000,
            "payee": "Mr Khumalo",
            "verification": "through_woza",
            "due_day": 1,
            "months_on_time": 36,
            "points_per_month": 4_500,
            "history_months": 36,
        },
        {
            "name": "Utilities",
            "category": "utilities",
            "amount_cents": 150_000,
            "payee": "Prepaid electricity R1 100 + water R400",
            "verification": "through_woza",
            "due_day": 1,
            "months_on_time": 36,
            "points_per_month": 1_500,
            "history_months": 36,
        },
        {
            "name": "Car finance",
            "category": "car",
            "amount_cents": 320_000,
            "payee": "[VEHICLE LENDER]",
            "verification": "bank_feed",
            "due_day": 1,
            "months_on_time": 36,
            "points_per_month": 3_200,
            "history_months": 36,
        },
    ]

    last_paid = "2026-10"
    bill_ids: dict[str, int] = {}
    for spec in bills_spec:
        bill = Bill(
            user_id=user.id,
            name=spec["name"],
            category=spec["category"],
            amount_cents=spec["amount_cents"],
            payee=spec["payee"],
            verification=spec["verification"],
            due_day=spec["due_day"],
            months_on_time=spec["months_on_time"],
            points_per_month=spec["points_per_month"],
        )
        db.add(bill)
        db.flush()
        bill_ids[spec["category"]] = bill.id

        periods = _periods_back(last_paid, spec["history_months"])
        for period in periods:
            paid_at = datetime(int(period[:4]), int(period[5:7]), 1, 10, 0, 0)
            db.add(
                Payment(
                    bill_id=bill.id,
                    period=period,
                    paid_at=paid_at,
                    on_time=True,
                    verified_by=spec["verification"],
                    points_awarded=spec["points_per_month"],
                )
            )

    db.add(
        GraceUse(
            bill_id=bill_ids["utilities"],
            period="2024-08",
            used_at=datetime(2024, 8, 5, 9, 0, 0),
        )
    )
    return user


def status_for_months(months: int) -> str:
    if months >= 48:
        return "Black"
    if months >= 24:
        return "Gold"
    if months >= 12:
        return "Silver"
    return "Starter"


def next_tier_info(months: int) -> dict:
    if months >= 48:
        return {"next": None, "months_needed": 0, "progress_num": 24, "progress_den": 24}
    if months >= 24:
        return {
            "next": "Black",
            "months_needed": 48 - months,
            "progress_num": months - 24,
            "progress_den": 24,
        }
    if months >= 12:
        return {
            "next": "Gold",
            "months_needed": 24 - months,
            "progress_num": months - 12,
            "progress_den": 12,
        }
    return {
        "next": "Silver",
        "months_needed": 12 - months,
        "progress_num": months,
        "progress_den": 12,
    }


def score_label(score: int) -> str:
    if score >= 750:
        return "Excellent"
    if score >= 730:
        return "Strong"
    return "Building"


REDEMPTION_ORDER = ["rent", "electricity", "data", "fuel", "groceries", "ebucks", "cash"]

REDEMPTION_RATES = {
    "rent": 1.5,
    "electricity": 1.5,
    "data": 1.0,
    "fuel": 1.0,
    "groceries": 1.0,
    "ebucks": 1.0,
    "cash": 0.5,
}

REDEMPTION_TITLES = {
    "rent": "Towards next rent",
    "electricity": "Prepaid electricity",
    "data": "Data and airtime",
    "fuel": "Fuel",
    "groceries": "Groceries",
    "ebucks": "eBucks",
    "cash": "Cash out to bank",
}

# approximate, update at launch
REDEEM_UNITS_PER_RAND = {
    "electricity": 0.31,  # units per rand
    "data": 0.0167,  # GB per rand
    "fuel": 0.045,  # litres per rand
}
