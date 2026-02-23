"""SQLAlchemy models for local OpenReach database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean, Float
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Lead(Base):
    """A lead / prospect to reach out to."""

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False, default="")
    instagram_handle = Column(String(200), nullable=False, default="")
    business_type = Column(String(200), nullable=False, default="")
    location = Column(String(500), nullable=False, default="")
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    website = Column(String(1000), nullable=False, default="")
    notes = Column(Text, nullable=True)
    pain_points = Column(Text, nullable=True)
    offer_context = Column(Text, nullable=True)
    # Cormass Leads integration
    cormass_business_id = Column(String(128), nullable=True)
    cormass_canvas_id = Column(Integer, nullable=True)
    # Source tracking
    source = Column(String(32), nullable=False, default="csv")  # csv, cormass_api, manual
    created_at = Column(DateTime, default=datetime.utcnow)


class OutreachLog(Base):
    """Log of outreach attempts."""

    __tablename__ = "outreach_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False)
    channel = Column(String(32), nullable=False, default="instagram_dm")
    state = Column(String(32), nullable=False, default="initiated")  # initiated, sent, delivered, replied, rejected, failed
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    """Agent session tracking."""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    messages_sent = Column(Integer, nullable=False, default=0)
    messages_failed = Column(Integer, nullable=False, default=0)
    leads_processed = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="running")  # running, completed, stopped, error
