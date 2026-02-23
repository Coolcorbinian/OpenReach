"""Local SQLite data store for OpenReach."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session as SASession, sessionmaker

from openreach.data.models import Base, Lead, OutreachLog, Session

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
        self._session_factory = sessionmaker(bind=self.engine)

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
    ) -> None:
        """Record an outreach attempt."""
        with self._session() as session:
            log = OutreachLog(
                lead_id=lead.get("id", 0),
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
