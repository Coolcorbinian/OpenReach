"""SQLAlchemy models for local OpenReach database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean, Float, JSON
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    """A configured outreach campaign."""

    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, default="Default Campaign")
    # Platform: instagram, linkedin, twitter, email (extensible)
    platform = Column(String(50), nullable=False, default="instagram")
    # Mode: static = template substitution, dynamic = LLM with scraped profile context
    mode = Column(String(20), nullable=False, default="dynamic")
    # User's prompt -- becomes the LLM system message (role definition)
    user_prompt = Column(Text, nullable=False, default="")
    # Additional notes / context for the LLM
    additional_notes = Column(Text, nullable=False, default="")
    # For static mode: the message template with {{placeholders}}
    message_template = Column(Text, nullable=False, default="")
    # Sender credentials (platform-specific)
    sender_username = Column(String(200), nullable=False, default="")
    sender_password = Column(String(500), nullable=False, default="")
    # Limits
    daily_limit = Column(Integer, nullable=False, default=50)
    session_limit = Column(Integer, nullable=False, default=15)
    delay_min = Column(Integer, nullable=False, default=45)
    delay_max = Column(Integer, nullable=False, default=180)
    # State
    is_active = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    # Scraped social profile cache (JSON blob)
    scraped_profile = Column(Text, nullable=True)
    scraped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class OutreachLog(Base):
    """Log of outreach attempts."""

    __tablename__ = "outreach_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False)
    campaign_id = Column(Integer, nullable=True)
    channel = Column(String(32), nullable=False, default="instagram_dm")
    state = Column(String(32), nullable=False, default="initiated")  # initiated, sent, delivered, replied, rejected, failed
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    """Agent session tracking."""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    messages_sent = Column(Integer, nullable=False, default=0)
    messages_failed = Column(Integer, nullable=False, default=0)
    leads_processed = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="running")  # running, completed, stopped, error


class ActivityLog(Base):
    """Real-time activity log for the agent -- displayed in the UI."""

    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, nullable=True)
    session_id = Column(Integer, nullable=True)
    level = Column(String(16), nullable=False, default="info")  # info, success, warning, error
    message = Column(Text, nullable=False, default="")
    details = Column(Text, nullable=True)  # optional extra data (JSON or text)
    created_at = Column(DateTime, default=datetime.utcnow)
