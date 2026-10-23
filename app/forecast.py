"""Woza Forecast — deterministic on-time and affordability model.

Recomputed from users / bills / payments / grace_uses on every read.
No external ML libraries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models import Bill, GraceUse, Payment, User
from app.seed import FORECAST_PERIOD, next_tier_info, status_for_months

DISCLOSURE = (
    "Predicted by Woza Forecast, a rules-based model. "
    "Woza does not make credit decisions; a human at the lender does."
)
DEMO_LATE_TAG = "demo_late"
WINDOW_WEIGHTS = ((3, 0.5), (6, 0.3), (12, 0.2))
TREND_MONTHS = 6
SEASONAL_MONTHS = {1, 12}
SEASONAL_ADJ = -8.0
GRACE_ADJ = -10.0
AMOUNT_SHARE_CUTOFF = 0.40
AMOUNT_ADJ = -5.0
PROB_MIN = 5
PROB_MAX = 99
BLACK_MONTHS = 48
INSTALMENT_SHARE = 0.30
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


@dataclass(frozen=True)
class Driver:
    text: str
    impact: float


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


def period_month(period: str) -> int:
    return int(period.split("-")[1])


def due_datetime(period: str, due_day: int) -> datetime:
    y, m = map(int, period.split("-"))
    day = min(max(int(due_day or 1), 1), 28)
    return datetime(y, m, day, 0, 0, 0)


def fmt_rands(rands: int) -> str:
    return "R" + f"{rands:,}".replace(",", " ")


def linear_slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def _pay_map(bill: Bill) -> dict[str, Payment]:
    return {p.period: p for p in (bill.payments or [])}


def _grace_map(bill: Bill) -> dict[str, GraceUse]:
    return {g.period: g for g in (bill.grace_uses or [])}


def days_before_due(bill: Bill, payment: Payment) -> int:
    due = due_datetime(payment.period, bill.due_day)
    paid = payment.paid_at
    if paid is None:
        return 0
    return (due.date() - paid.date()).days


def history_end(bill: Bill, target_period: str) -> str:
    """Last month that has a payment or grace, else the month before target."""
    periods = [p.period for p in (bill.payments or [])] + [
        g.period for g in (bill.grace_uses or [])
    ]
    if target_period in periods:
        return target_period
    prior = period_sub_month(target_period)
    if periods:
        return max(max(periods), prior)
    return prior


def on_time_rate(bill: Bill, end_period: str, months: int) -> float:
    pays = _pay_map(bill)
    graces = _grace_map(bill)
    samples: list[float] = []
    for period in periods_ending(end_period, months):
        pay = pays.get(period)
        if pay is not None:
            samples.append(1.0 if pay.on_time else 0.0)
            continue
        if period in graces:
            continue
    if not samples:
        return 1.0
    return sum(samples) / len(samples)


def consecutive_on_time(bill: Bill, end_period: str) -> int:
    pays = _pay_map(bill)
    graces = _grace_map(bill)
    streak = 0
    period = end_period
    for _ in range(60):
        pay = pays.get(period)
        if pay is not None and pay.on_time:
            streak += 1
            period = period_sub_month(period)
            continue
        if period in graces:
            period = period_sub_month(period)
            continue
        if pay is not None and not pay.on_time:
            break
        if period not in pays and period not in graces:
            break
        break
    return streak


def trend_adjustment(bill: Bill, end_period: str) -> float:
    pays = _pay_map(bill)
    values: list[float] = []
    for period in periods_ending(end_period, TREND_MONTHS):
        pay = pays.get(period)
        if pay is None:
            continue
        values.append(float(days_before_due(bill, pay)))
    slope = linear_slope(values)
    # Paying later (negative slope of days-before-due) lowers probability.
    return max(-10.0, min(10.0, slope * 1.5))


def grace_count_12m(bill: Bill, end_period: str) -> int:
    window = set(periods_ending(end_period, 12))
    return sum(1 for g in (bill.grace_uses or []) if g.period in window)


def latest_late(bill: Bill, end_period: str) -> Payment | None:
    pays = _pay_map(bill)
    period = end_period
    for _ in range(12):
        pay = pays.get(period)
        if pay is not None and not pay.on_time:
            return pay
        period = period_sub_month(period)
    return None


def display_bill_name(bill: Bill) -> str:
    if bill.category == "car":
        return "Car instalment"
    raw = (bill.name or "This bill").strip()
    return raw[:1].upper() + raw[1:] if raw else "This bill"


def driver_noun(bill: Bill) -> str:
    name = display_bill_name(bill)
    if name == "Car instalment":
        return "car instalment"
    return name.lower()


def clamp_prob(value: float) -> int:
    return int(round(max(PROB_MIN, min(PROB_MAX, value))))


def pair_drivers(drivers: list[Driver]) -> list[str]:
    """Strongest positive and strongest negative, at most one of each."""
    pos = [d for d in drivers if d.impact > 0]
    neg = [d for d in drivers if d.impact < 0]
    out: list[str] = []
    if pos:
        out.append(max(pos, key=lambda d: d.impact).text)
    if neg:
        out.append(min(neg, key=lambda d: d.impact).text)
    return out


def is_demo_late(verified_by: str | None) -> bool:
    tag = verified_by or ""
    return tag == DEMO_LATE_TAG or tag.startswith(DEMO_LATE_TAG + ":")


def affordability_band(probability: int) -> str:
    if probability >= 80:
        return "High"
    if probability >= 55:
        return "Medium"
    return "Low"


def months_to_next_status(user: User, probability: int) -> tuple[str, int]:
    info = next_tier_info(user.months_on_time)
    nxt = info.get("next") or status_for_months(max(user.months_on_time, BLACK_MONTHS))
    needed = int(info.get("months_needed") or 0)
    if needed <= 0:
        return nxt, 0
    p = max(probability, PROB_MIN) / 100.0
    return nxt, max(1, int(round(needed / p)))


def verified_obligation_cents(user: User, bills: list[Bill]) -> int:
    total = 0
    for bill in bills:
        if bill.verification == "through_woza":
            total += bill.amount_cents
        elif bill.verification == "bank_feed" and user.bank_consent_active:
            total += bill.amount_cents
    return total


def has_simulated_late(bills: list[Bill]) -> bool:
    return any(is_demo_late(p.verified_by) for bill in bills for p in (bill.payments or []))


def forecast_bill(
    bill: Bill,
    *,
    total_cents: int,
    target_period: str,
) -> dict:
    end = history_end(bill, target_period)
    weighted = 0.0
    rates: dict[str, float] = {}
    for months, weight in WINDOW_WEIGHTS:
        rate = on_time_rate(bill, end, months)
        rates[f"on_time_rate_{months}m"] = round(rate * 100, 1)
        weighted += rate * 100.0 * weight

    trend_adj = trend_adjustment(bill, end)
    seasonal_adj = SEASONAL_ADJ if period_month(target_period) in SEASONAL_MONTHS else 0.0
    n_grace = grace_count_12m(bill, end)
    grace_adj = n_grace * GRACE_ADJ
    share = (bill.amount_cents / total_cents) if total_cents else 0.0
    amount_adj = AMOUNT_ADJ if share > AMOUNT_SHARE_CUTOFF else 0.0

    raw = weighted + trend_adj + seasonal_adj + grace_adj + amount_adj
    probability = clamp_prob(raw)

    name = display_bill_name(bill)
    noun = driver_noun(bill)
    streak = consecutive_on_time(bill, end)
    drivers: list[Driver] = []
    if streak >= 3:
        drivers.append(
            Driver(
                f"Paid {noun} on or before the 1st for {streak} straight months (+)",
                float(streak),
            )
        )
    late = latest_late(bill, end)
    if late is not None:
        label = MONTH_SHORT[period_month(late.period) - 1]
        drivers.append(
            Driver(
                f"{name} marked late in {label} (−)",
                -25.0,
            )
        )
    if n_grace:
        recent = max(
            (g for g in (bill.grace_uses or []) if g.period in set(periods_ending(end, 12))),
            key=lambda g: g.period,
            default=None,
        )
        when = MONTH_SHORT[period_month(recent.period) - 1] if recent else "the last year"
        drivers.append(
            Driver(
                f"{name} used a grace month in {when} (−)",
                grace_adj,
            )
        )
    if amount_adj:
        pct = int(round(share * 100))
        drivers.append(
            Driver(
                f"{name} is {pct}% of your monthly bills (−)",
                amount_adj,
            )
        )
    if abs(trend_adj) >= 0.5:
        if trend_adj < 0:
            drivers.append(
                Driver(
                    f"{name} is being paid later each month (−)",
                    trend_adj,
                )
            )
        else:
            drivers.append(
                Driver(
                    f"{name} is being paid earlier each month (+)",
                    trend_adj,
                )
            )
    if seasonal_adj:
        drivers.append(
            Driver(
                "December and January carry a seasonal adjustment (−)",
                seasonal_adj,
            )
        )
    if not drivers:
        drivers.append(
            Driver(
                f"{name} on-time rate is {probability}% next month (predicted) (+)",
                float(probability),
            )
        )

    return {
        "bill_id": bill.id,
        "name": name,
        "category": bill.category,
        "amount_cents": bill.amount_cents,
        "probability_on_time_next_month": probability,
        "drivers": pair_drivers(drivers),
        "components": {
            **rates,
            "trend_adj": round(trend_adj, 2),
            "seasonal_adj": seasonal_adj,
            "grace_adj": grace_adj,
            "amount_adj": amount_adj,
            "amount_share": round(share, 3),
        },
    }


def predicted_affordability(user: User, bills: list[Bill], probability: int) -> dict:
    obligations = verified_obligation_cents(user, bills)
    ceiling = int(round((obligations / 100.0) * INSTALMENT_SHARE * (probability / 100.0)))
    band = affordability_band(probability)
    return {
        "band": band,
        "instalment_ceiling_rands": ceiling,
        "instalment_ceiling_display": fmt_rands(ceiling),
        "verified_monthly_obligations_cents": obligations,
        "disclosure": DISCLOSURE,
    }


def build_forecast(
    user: User,
    bills: list[Bill],
    *,
    target_period: str = FORECAST_PERIOD,
) -> dict:
    bills = list(bills)
    total = sum(b.amount_cents for b in bills) or 1
    per_bill = [
        forecast_bill(bill, total_cents=total, target_period=target_period) for bill in bills
    ]
    weighted_num = sum(row["probability_on_time_next_month"] * row["amount_cents"] for row in per_bill)
    overall_p = clamp_prob(weighted_num / total) if per_bill else PROB_MIN
    nxt, months = months_to_next_status(user, overall_p)
    afford = predicted_affordability(user, bills, overall_p)
    overall_drivers: list[str] = []
    for row in per_bill:
        overall_drivers.extend(row["drivers"][:1])
    overall_drivers = overall_drivers[:3]
    if not overall_drivers:
        overall_drivers = [
            f"Overall on-time probability next month is {overall_p}% (predicted)"
        ]

    y, m = map(int, target_period.split("-"))
    return {
        "disclosure": DISCLOSURE,
        "method": "woza_forecast_rules",
        "target_period": target_period,
        "target_month_label": f"{MONTH_SHORT[m - 1]} {y}",
        "simulated_late": has_simulated_late(bills),
        "bills": per_bill,
        "overall": {
            "probability_on_time_next_month": overall_p,
            "months_to_next_status": months,
            "next_status": nxt,
            "current_status": status_for_months(user.months_on_time),
            "drivers": overall_drivers,
            "predicted_affordability_band": afford["band"],
            "predicted_instalment_ceiling_rands": afford["instalment_ceiling_rands"],
            "predicted_instalment_ceiling_display": afford["instalment_ceiling_display"],
        },
        "predicted_affordability": afford,
    }


def due_plus_days(period: str, due_day: int, days: int) -> datetime:
    return due_datetime(period, due_day) + timedelta(days=days)
