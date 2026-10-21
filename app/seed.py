from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Bill, GraceUse, Payment, Redemption, User, engine

CURRENT_PERIOD = "2026-11"
DEMO_NOW = datetime(2026, 10, 21, 9, 0, 0)
DEMO_VERSION = 3

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


def drop_and_reseed() -> None:
    from app.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session(bind=engine)
    try:
        _seed(db)
        db.commit()
    finally:
        db.close()


def seed_if_empty(db: Session) -> None:
    user = db.query(User).first()
    if user is None:
        _seed(db)
        db.commit()
        return
    if user.demo_version != DEMO_VERSION:
        drop_and_reseed()


def _seed(db: Session) -> None:
    user = User(
        name="Thandi Mokoena",
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
            "months_on_time": 30,
            "points_per_month": 1_500,
            "history_months": 30,
        },
        {
            "name": "Car Payments",
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


REDEMPTION_RATES = {
    "rent": 1.5,
    "ebucks": 1.0,
    "airtime": 1.0,
    "cash": 0.5,
}

REDEEM_VALUE_LABELS = {
    "rent": "off rent",
    "ebucks": "in eBucks",
    "airtime": "airtime",
    "cash": "cash out",
}
