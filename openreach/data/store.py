"""Local SQLite data store for OpenReach."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session as SASession, sessionmaker

from openreach.data.models import Base, Lead, OutreachLog, Session, Campaign, ActivityLog, AgentTurnLog

logger = logging.getLogger(__name__)


class DataStore:
    """Local SQLite database operations."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            from openreach.config import CONFIG_DIR

            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            db_path = str(CONFIG_DIR / "openreach.db")

        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self._migrate_schema()
        self._session_factory = sessionmaker(bind=self.engine)

    def _migrate_schema(self) -> None:
        """Add new columns to existing tables if they don't exist (lightweight migration)."""
        import sqlite3
        db_url = str(self.engine.url).replace("sqlite:///", "")
        conn = sqlite3.connect(db_url)
        cursor = conn.cursor()

        # Mapping: (table, column, type, default)
        migrations = [
            ("leads", "scraped_profile", "TEXT", None),
            ("leads", "scraped_at", "DATETIME", None),
            ("leads", "phone_number", "TEXT", "''"),
            ("leads", "email", "TEXT", "''"),
            ("leads", "social_handles", "TEXT", "'{}'"),
            ("leads", "enrichment_json", "TEXT", None),
            ("outreach_log", "campaign_id", "INTEGER", None),
            ("sessions", "campaign_id", "INTEGER", None),
            ("campaigns", "context_canvas_ids", "TEXT", "''"),
            ("campaigns", "llm_provider", "TEXT", "'openrouter'"),
            ("campaigns", "llm_model", "TEXT", "''"),
        ]

        for table, column, col_type, default in migrations:
            try:
                cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                # Column doesn't exist, add it
                default_clause = f" DEFAULT {default}" if default is not None else ""
                sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}"
                cursor.execute(sql)
                logger.info("Migration: added %s.%s (%s)", table, column, col_type)

        conn.commit()
        conn.close()

    def _session(self) -> SASession:
        return self._session_factory()

    # --- Leads ---

    def add_lead(self, lead_data: dict[str, Any]) -> Lead:
        """Add a single lead to the database."""
        with self._session() as session:
            lead = Lead(**lead_data)
            session.add(lead)
            session.commit()
            session.refresh(lead)
            return lead

    def add_leads(self, leads: list[dict[str, Any]]) -> int:
        """Add multiple leads. Returns count of added leads."""
        with self._session() as session:
            count = 0
            for data in leads:
                session.add(Lead(**data))
                count += 1
            session.commit()
            return count

    def get_leads(
        self,
        source: str | None = None,
        canvas_id: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get leads, optionally filtered by source or canvas ID."""
        with self._session() as session:
            query = session.query(Lead)
            if source:
                query = query.filter(Lead.source == source)
            if canvas_id is not None:
                query = query.filter(Lead.cormass_canvas_id == canvas_id)
            query = query.order_by(Lead.created_at.desc()).limit(limit)

            return [
                {
                    "id": l.id,
                    "name": l.name,
                    "instagram_handle": l.instagram_handle,
                    "phone_number": getattr(l, "phone_number", ""),
                    "email": getattr(l, "email", ""),
                    "social_handles": getattr(l, "social_handles", "{}"),
                    "business_type": l.business_type,
                    "location": l.location,
                    "rating": l.rating,
                    "review_count": l.review_count,
                    "website": l.website,
                    "notes": l.notes,
                    "pain_points": l.pain_points,
                    "offer_context": l.offer_context,
                    "source": l.source,
                    "cormass_business_id": l.cormass_business_id,
                    "cormass_canvas_id": l.cormass_canvas_id,
                }
                for l in query.all()
            ]

    def get_unreached_leads(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get leads that haven't been contacted yet."""
        with self._session() as session:
            subquery = session.query(OutreachLog.lead_id).filter(
                OutreachLog.state.in_(["sent", "delivered", "replied"])
            ).subquery()

            leads = (
                session.query(Lead)
                .filter(~Lead.id.in_(subquery))
                .order_by(Lead.created_at.asc())
                .limit(limit)
                .all()
            )

            return [
                {
                    "id": l.id,
                    "name": l.name,
                    "instagram_handle": l.instagram_handle,
                    "business_type": l.business_type,
                    "location": l.location,
                    "rating": l.rating,
                    "review_count": l.review_count,
                    "website": l.website,
                    "notes": l.notes,
                    "pain_points": l.pain_points,
                    "offer_context": l.offer_context,
                    "source": l.source,
                    "cormass_business_id": l.cormass_business_id,
                }
                for l in leads
            ]

    # --- Outreach Logging ---

    def record_outreach(
        self,
        lead: dict[str, Any],
        state: str,
        message: str | None = None,
        error: str | None = None,
        campaign_id: int | None = None,
    ) -> None:
        """Record an outreach attempt."""
        with self._session() as session:
            log = OutreachLog(
                lead_id=lead.get("id", 0),
                campaign_id=campaign_id,
                channel="instagram_dm",
                state=state,
                message=message,
                error=error,
            )
            session.add(log)
            session.commit()

    def get_today_message_count(self) -> int:
        """Get the number of messages sent today."""
        with self._session() as session:
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            count = (
                session.query(func.count(OutreachLog.id))
                .filter(
                    OutreachLog.state == "sent",
                    OutreachLog.created_at >= today,
                )
                .scalar()
            )
            return count or 0

    # --- Sessions ---

    def start_session(self) -> int:
        """Start a new agent session. Returns session ID."""
        with self._session() as session:
            s = Session(status="running")
            session.add(s)
            session.commit()
            session.refresh(s)
            return s.id

    def end_session(self, session_id: int, stats: dict[str, int]) -> None:
        """End an agent session with stats."""
        with self._session() as session:
            s = session.query(Session).filter(Session.id == session_id).first()
            if s:
                s.ended_at = datetime.utcnow()
                s.messages_sent = stats.get("messages_sent", 0)
                s.messages_failed = stats.get("messages_failed", 0)
                s.leads_processed = stats.get("leads_processed", 0)
                s.status = stats.get("status", "completed")
                session.commit()

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics."""
        with self._session() as session:
            total_leads = session.query(func.count(Lead.id)).scalar() or 0
            total_sent = (
                session.query(func.count(OutreachLog.id))
                .filter(OutreachLog.state == "sent")
                .scalar()
                or 0
            )
            total_replied = (
                session.query(func.count(OutreachLog.id))
                .filter(OutreachLog.state == "replied")
                .scalar()
                or 0
            )
            total_failed = (
                session.query(func.count(OutreachLog.id))
                .filter(OutreachLog.state == "failed")
                .scalar()
                or 0
            )
            today_sent = self.get_today_message_count()

            return {
                "total_leads": total_leads,
                "total_sent": total_sent,
                "total_replied": total_replied,
                "total_failed": total_failed,
                "today_sent": today_sent,
                "reply_rate": round(total_replied / total_sent * 100, 1) if total_sent > 0 else 0.0,
            }

    # --- Campaigns ---

    def create_campaign(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new campaign/task. Returns the campaign dict."""
        with self._session() as session:
            campaign = Campaign(
                name=data.get("name", "Default Task"),
                platform=data.get("platform", "browser"),
                mode=data.get("mode", "agent"),
                user_prompt=data.get("user_prompt", ""),
                additional_notes=data.get("additional_notes", ""),
                message_template=data.get("message_template", ""),
                sender_username=data.get("sender_username", ""),
                sender_password=data.get("sender_password", ""),
                context_canvas_ids=data.get("context_canvas_ids", ""),
                llm_provider=data.get("llm_provider", "openrouter"),
                llm_model=data.get("llm_model", ""),
                daily_limit=data.get("daily_limit", 50),
                session_limit=data.get("session_limit", 15),
                delay_min=data.get("delay_min", 45),
                delay_max=data.get("delay_max", 180),
                is_active=data.get("is_active", False),
            )
            session.add(campaign)
            session.commit()
            session.refresh(campaign)
            return self._campaign_to_dict(campaign)

    def update_campaign(self, campaign_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        """Update a campaign. Returns updated dict or None."""
        with self._session() as session:
            campaign = session.query(Campaign).filter(Campaign.id == campaign_id).first()
            if not campaign:
                return None
            for key in (
                "name", "platform", "mode", "user_prompt", "additional_notes",
                "message_template", "sender_username", "sender_password",
                "context_canvas_ids", "llm_provider", "llm_model",
                "daily_limit", "session_limit", "delay_min", "delay_max", "is_active",
            ):
                if key in data:
                    setattr(campaign, key, data[key])
            campaign.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(campaign)
            return self._campaign_to_dict(campaign)

    def get_campaign(self, campaign_id: int) -> dict[str, Any] | None:
        """Get a single campaign by ID."""
        with self._session() as session:
            campaign = session.query(Campaign).filter(Campaign.id == campaign_id).first()
            if not campaign:
                return None
            return self._campaign_to_dict(campaign)

    def get_campaigns(self) -> list[dict[str, Any]]:
        """Get all campaigns."""
        with self._session() as session:
            campaigns = session.query(Campaign).order_by(Campaign.created_at.desc()).all()
            return [self._campaign_to_dict(c) for c in campaigns]

    def get_active_campaign(self) -> dict[str, Any] | None:
        """Get the currently active campaign."""
        with self._session() as session:
            campaign = session.query(Campaign).filter(Campaign.is_active == True).first()
            if not campaign:
                return None
            return self._campaign_to_dict(campaign)

    def delete_campaign(self, campaign_id: int) -> bool:
        """Delete a campaign. Returns True if deleted."""
        with self._session() as session:
            campaign = session.query(Campaign).filter(Campaign.id == campaign_id).first()
            if not campaign:
                return False
            session.delete(campaign)
            session.commit()
            return True

    def _campaign_to_dict(self, c: Campaign) -> dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "platform": c.platform,
            "mode": c.mode,
            "user_prompt": c.user_prompt,
            "additional_notes": c.additional_notes,
            "message_template": c.message_template,
            "sender_username": c.sender_username,
            "sender_password": c.sender_password,
            "context_canvas_ids": getattr(c, "context_canvas_ids", ""),
            "llm_provider": getattr(c, "llm_provider", "openrouter"),
            "llm_model": getattr(c, "llm_model", ""),
            "daily_limit": c.daily_limit,
            "session_limit": c.session_limit,
            "delay_min": c.delay_min,
            "delay_max": c.delay_max,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }

    # --- Activity Log ---

    def log_activity(
        self,
        message: str,
        level: str = "info",
        campaign_id: int | None = None,
        session_id: int | None = None,
        details: str | None = None,
    ) -> None:
        """Write an entry to the activity log."""
        with self._session() as session:
            entry = ActivityLog(
                campaign_id=campaign_id,
                session_id=session_id,
                level=level,
                message=message,
                details=details,
            )
            session.add(entry)
            session.commit()

    def get_activity_log(
        self,
        campaign_id: int | None = None,
        limit: int = 50,
        after_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent activity log entries."""
        with self._session() as session:
            query = session.query(ActivityLog)
            if campaign_id is not None:
                query = query.filter(ActivityLog.campaign_id == campaign_id)
            if after_id is not None:
                query = query.filter(ActivityLog.id > after_id)
            query = query.order_by(ActivityLog.id.desc()).limit(limit)
            entries = query.all()
            return [
                {
                    "id": e.id,
                    "level": e.level,
                    "message": e.message,
                    "details": e.details,
                    "campaign_id": e.campaign_id,
                    "session_id": e.session_id,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in reversed(entries)  # chronological order
            ]

    # --- Lead profile cache ---

    def update_lead_profile(self, lead_id: int, profile_data: dict[str, Any]) -> None:
        """Cache scraped social profile data for a lead."""
        with self._session() as session:
            lead = session.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                lead.scraped_profile = json.dumps(profile_data)
                lead.scraped_at = datetime.utcnow()
                session.commit()

    def get_lead_cached_profile(self, lead_id: int, max_age_days: int = 7) -> dict[str, Any] | None:
        """Get cached profile if fresh enough, else None."""
        with self._session() as session:
            lead = session.query(Lead).filter(Lead.id == lead_id).first()
            if not lead or not lead.scraped_profile or not lead.scraped_at:
                return None
            age = datetime.utcnow() - lead.scraped_at
            if age > timedelta(days=max_age_days):
                return None
            try:
                return json.loads(lead.scraped_profile)
            except (json.JSONDecodeError, TypeError):
                return None

    # --- Agent Turn Logging ---

    def log_agent_turn(
        self,
        campaign_id: int | None,
        session_id: int | None,
        turn_number: int,
        role: str,
        content: str = "",
        tool_name: str | None = None,
        tool_args: str | None = None,
        tool_result: str | None = None,
        tokens_used: int = 0,
    ) -> None:
        """Record a single agent conversation turn."""
        with self._session() as session:
            entry = AgentTurnLog(
                campaign_id=campaign_id,
                session_id=session_id,
                turn_number=turn_number,
                role=role,
                content=content[:5000] if content else "",
                tool_name=tool_name,
                tool_args=tool_args[:2000] if tool_args else None,
                tool_result=tool_result[:2000] if tool_result else None,
                tokens_used=tokens_used,
            )
            session.add(entry)
            session.commit()

    def get_agent_turns(
        self,
        campaign_id: int | None = None,
        session_id: int | None = None,
        after_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get agent turn records for display in the UI."""
        with self._session() as session:
            query = session.query(AgentTurnLog)
            if campaign_id is not None:
                query = query.filter(AgentTurnLog.campaign_id == campaign_id)
            if session_id is not None:
                query = query.filter(AgentTurnLog.session_id == session_id)
            if after_id is not None:
                query = query.filter(AgentTurnLog.id > after_id)
            query = query.order_by(AgentTurnLog.id.desc()).limit(limit)
            entries = query.all()
            return [
                {
                    "id": e.id,
                    "turn_number": e.turn_number,
                    "role": e.role,
                    "content": e.content,
                    "tool_name": e.tool_name,
                    "tool_args": e.tool_args,
                    "tool_result": e.tool_result,
                    "tokens_used": e.tokens_used,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in reversed(entries)
            ]
