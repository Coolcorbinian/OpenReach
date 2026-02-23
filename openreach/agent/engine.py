"""Core agent loop -- orchestrates LLM planning with browser execution."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from openreach.browser.session import BrowserSession
from openreach.data.store import DataStore
from openreach.llm.client import OllamaClient

logger = logging.getLogger(__name__)


class AgentState(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentStats:
    messages_sent: int = 0
    messages_failed: int = 0
    replies_received: int = 0
    session_start: float = 0.0
    leads_processed: int = 0


@dataclass
class AgentConfig:
    delay_min: int = 45
    delay_max: int = 180
    daily_limit: int = 50
    session_limit: int = 15


class AgentEngine:
    """Main agent loop that coordinates LLM decisions with browser actions."""

    def __init__(
        self,
        llm: OllamaClient,
        browser: BrowserSession,
        store: DataStore,
        config: AgentConfig | None = None,
    ) -> None:
        self.llm = llm
        self.browser = browser
        self.store = store
        self.config = config or AgentConfig()
        self.state = AgentState.IDLE
        self.stats = AgentStats()
        self._stop_requested = False

    async def start(self, leads: list[dict[str, Any]]) -> AgentStats:
        """Run the agent loop over a list of leads."""
        import time
        import random

        self.state = AgentState.IDLE
        self.stats = AgentStats()
        self.stats.session_start = time.time()
        self._stop_requested = False

        logger.info("Agent starting with %d leads", len(leads))

        for i, lead in enumerate(leads):
            if self._stop_requested:
                logger.info("Stop requested, halting agent")
                break

            if self.stats.messages_sent >= self.config.session_limit:
                logger.info("Session limit reached (%d)", self.config.session_limit)
                break

            # Check daily limit from store
            today_count = self.store.get_today_message_count()
            if today_count >= self.config.daily_limit:
                logger.info("Daily limit reached (%d)", self.config.daily_limit)
                break

            try:
                # Plan the message
                self.state = AgentState.PLANNING
                message = await self._plan_message(lead)

                if not message:
                    logger.warning("LLM returned empty message for lead %s, skipping", lead.get("name", "?"))
                    continue

                # Execute the outreach
                self.state = AgentState.EXECUTING
                success = await self._execute_outreach(lead, message)

                if success:
                    self.stats.messages_sent += 1
                    self.store.record_outreach(lead, "sent", message)
                    logger.info("Message sent to %s (%d/%d)", lead.get("name", "?"), i + 1, len(leads))
                else:
                    self.stats.messages_failed += 1
                    self.store.record_outreach(lead, "failed", message)
                    logger.warning("Failed to send to %s", lead.get("name", "?"))

                # Human-like delay
                self.state = AgentState.WAITING
                delay = random.randint(self.config.delay_min, self.config.delay_max)
                logger.debug("Waiting %d seconds before next message", delay)
                await asyncio.sleep(delay)

            except Exception as e:
                self.state = AgentState.ERROR
                logger.error("Error processing lead %s: %s", lead.get("name", "?"), e)
                self.stats.messages_failed += 1
                self.store.record_outreach(lead, "failed", error=str(e))

            self.stats.leads_processed += 1

        self.state = AgentState.STOPPED
        logger.info(
            "Agent finished. Sent: %d, Failed: %d, Processed: %d",
            self.stats.messages_sent,
            self.stats.messages_failed,
            self.stats.leads_processed,
        )
        return self.stats

    def stop(self) -> None:
        """Request the agent to stop after the current lead."""
        self._stop_requested = True

    async def _plan_message(self, lead: dict[str, Any]) -> str | None:
        """Use the LLM to generate a personalized outreach message."""
        from openreach.llm.prompts import build_outreach_prompt

        prompt = build_outreach_prompt(lead)
        response = await self.llm.generate(prompt)

        if not response or not response.strip():
            return None

        return response.strip()

    async def _execute_outreach(self, lead: dict[str, Any], message: str) -> bool:
        """Send the message via the browser."""
        handle = lead.get("instagram_handle", "")
        if not handle:
            logger.warning("No Instagram handle for lead %s", lead.get("name", "?"))
            return False

        return await self.browser.send_instagram_dm(handle, message)
