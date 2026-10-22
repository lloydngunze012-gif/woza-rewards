from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DATABASE_URL = "sqlite:///./woza.db"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    status = Column(String, nullable=False)
    months_on_time = Column(Integer, default=0)
    score = Column(Integer, default=742)
    points = Column(Integer, default=0)
    lifetime_points = Column(Integer, default=0)
    redeemed_points = Column(Integer, default=0)
    woza_cash_cents = Column(Integer, default=0)
    grace_months = Column(Integer, default=0)
    grace_months_earned = Column(Integer, default=0)
    demo_version = Column(Integer, default=0)
    bank_consent_active = Column(Boolean, default=True)

    bills = relationship("Bill", back_populates="user")
    redemptions = relationship("Redemption", back_populates="user")


class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    payee = Column(String, nullable=False)
    verification = Column(String, nullable=False)
    due_day = Column(Integer, default=1)
    months_on_time = Column(Integer, default=0)
    points_per_month = Column(Integer, default=0)

    user = relationship("User", back_populates="bills")
    payments = relationship("Payment", back_populates="bill")
    grace_uses = relationship("GraceUse", back_populates="bill")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=False)
    period = Column(String, nullable=False)
    paid_at = Column(DateTime, nullable=False)
    on_time = Column(Boolean, default=True)
    verified_by = Column(String, nullable=False)
    points_awarded = Column(Integer, default=0)

    bill = relationship("Bill", back_populates="payments")


class GraceUse(Base):
    __tablename__ = "grace_uses"

    id = Column(Integer, primary_key=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=False)
    period = Column(String, nullable=False)
    used_at = Column(DateTime, default=datetime.utcnow)

    bill = relationship("Bill", back_populates="grace_uses")


class Redemption(Base):
    __tablename__ = "redemptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    option = Column(String, nullable=False)
    points_spent = Column(Integer, nullable=False)
    value_cents = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="redemptions")


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
