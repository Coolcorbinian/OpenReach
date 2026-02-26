"""SQLAlchemy models for local OpenReach database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean, Float, JSON
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    """A configured outreach task (agent-driven).

    Legacy name kept as 'campaigns' table for backward compatibility.
    Conceptually this is now a 'Task' -- a natural-language instruction
    for the agent to execute using browser tools and lead data.
    """

    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, default="Default Task")
    # --- Agent task definition ---
    # The user's natural language prompt that defines what the agent should do
    user_prompt = Column(Text, nullable=False, default="")
    # Additional notes / context for the agent
    additional_notes = Column(Text, nullable=False, default="")
    # --- Legacy fields (kept for migration compatibility) ---
    platform = Column(String(50), nullable=False, default="browser")
    mode = Column(String(20), nullable=False, default="agent")
    message_template = Column(Text, nullable=False, default="")
    sender_username = Column(String(200), nullable=False, default="")
    sender_password = Column(String(500), nullable=False, default="")
    # --- Lead source context ---
    # Comma-separated canvas IDs to use as lead source
    context_canvas_ids = Column(Text, nullable=False, default="")
    # --- LLM configuration ---
    llm_provider = Column(String(32), nullable=False, default="openrouter")
    llm_model = Column(String(200), nullable=False, default="")
    # --- Limits ---
    daily_limit = Column(Integer, nullable=False, default=50)
    session_limit = Column(Integer, nullable=False, default=15)
    delay_min = Column(Integer, nullable=False, default=45)
    delay_max = Column(Integer, nullable=False, default=180)
    # --- State ---
    is_active = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Lead(Base):
    """A lead / prospect to reach out to."""

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False, default="")
    instagram_handle = Column(String(200), nullable=False, default="")
    phone_number = Column(String(100), nullable=False, default="")
    email = Column(String(500), nullable=False, default="")
    # JSON dict of social handles: {"instagram": "x", "linkedin": "y", "twitter": "z"}
    social_handles = Column(Text, nullable=False, default="{}")
    business_type = Column(String(200), nullable=False, default="")
    location = Column(String(500), nullable=False, default="")
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    website = Column(String(1000), nullable=False, default="")
    notes = Column(Text, nullable=True)
    pain_points = Column(Text, nullable=True)
    offer_context = Column(Text, nullable=True)
    # Enrichment data from Cormass Leads (JSON blob with full raw data)
    enrichment_json = Column(Text, nullable=True)
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
    channel = Column(String(32), nullable=False, default="browser")
    state = Column(String(32), nullable=False, default="initiated")
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
    status = Column(String(32), nullable=False, default="running")


class ActivityLog(Base):
    """Real-time activity log for the agent -- displayed in the UI."""

    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, nullable=True)
    session_id = Column(Integer, nullable=True)
    level = Column(String(16), nullable=False, default="info")
    message = Column(Text, nullable=False, default="")
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentTurnLog(Base):
    """Record of each LLM turn in the agent conversation -- for UI display and debugging."""

    __tablename__ = "agent_turns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, nullable=True)
    session_id = Column(Integer, nullable=True)
    turn_number = Column(Integer, nullable=False, default=0)
    role = Column(String(32), nullable=False, default="assistant")  # assistant, tool, error
    content = Column(Text, nullable=False, default="")
    tool_name = Column(String(100), nullable=True)
    tool_args = Column(Text, nullable=True)  # JSON
    tool_result = Column(Text, nullable=True)
    tokens_used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
