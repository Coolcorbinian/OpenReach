"""Core agent loop -- orchestrates LLM planning with browser execution.

The AgentEngine coordinates:
1. Campaign configuration (platform, mode, prompt, credentials)
2. Lead queue processing with rate limiting
3. LLM message generation (dynamic mode) or template substitution (static mode)
4. Social profile scraping for dynamic context
5. Browser-based message delivery
6. Activity logging for real-time UI feedback
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from openreach.browser.session import BrowserSession
from openreach.data.store import DataStore
from openreach.llm.client import OllamaClient
from openreach.llm.prompts import build_system_prompt, build_static_message, build_dynamic_prompt

logger = logging.getLogger(__name__)


class AgentState(Enum):
    IDLE = "idle"
    STARTING = "starting"
    LOGGING_IN = "logging_in"
    PLANNING = "planning"
    SCRAPING = "scraping"
    EXECUTING = "executing"
    WAITING = "waiting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentStats:
    messages_sent: int = 0
    messages_failed: int = 0
    leads_processed: int = 0
    session_start: float = 0.0


class AgentEngine:
    """Main agent loop that coordinates LLM decisions with browser actions.

    Lifecycle:
        1. start() is called with a campaign dict and list of leads
        2. Browser launches, logs in if needed
        3. For each lead:
           a. (Dynamic mode) Scrape social profile for context
           b. Generate message via LLM or template
           c. Send via browser automation
           d. Log activity and outreach result
           e. Wait a human-like delay
        4. stop() can be called externally to halt after current lead
    """

    def __init__(
        self,
        llm: OllamaClient,
        browser: BrowserSession,
        store: DataStore,
    ) -> None:
        self.llm = llm
        self.browser = browser
        self.store = store
        self.state = AgentState.IDLE
        self.stats = AgentStats()
        self._stop_requested = False
        self._campaign: dict[str, Any] | None = None
        self._session_id: int | None = None

    async def start(self, campaign: dict[str, Any], leads: list[dict[str, Any]]) -> AgentStats:
        """Run the agent loop over a list of leads using the given campaign.

        Args:
            campaign: Campaign configuration dict from the database
            leads: List of lead dicts to process

        Returns:
            AgentStats with final counts
        """
        self._campaign = campaign
        self.state = AgentState.STARTING
        self.stats = AgentStats()
        self.stats.session_start = time.time()
        self._stop_requested = False

        campaign_id = campaign.get("id")
        platform = campaign.get("platform", "instagram")
        mode = campaign.get("mode", "dynamic")
        delay_min = campaign.get("delay_min", 45)
        delay_max = campaign.get("delay_max", 180)
        daily_limit = campaign.get("daily_limit", 50)
        session_limit = campaign.get("session_limit", 15)

        # Start a DB session
        self._session_id = self.store.start_session()
        self._log("info", f"Agent starting -- {len(leads)} leads, platform={platform}, mode={mode}")

        try:
            # Launch browser
            await self.browser.launch(platform=platform)
            platform_session = self.browser.get_platform_session(platform)

            # Login if needed
            self.state = AgentState.LOGGING_IN
            logged_in = await platform_session.is_logged_in()

            if not logged_in:
                username = campaign.get("sender_username", "")
                password = campaign.get("sender_password", "")

                if not username or not password:
                    self._log("error", "No sender credentials configured. Cannot log in.")
                    self.state = AgentState.ERROR
                    return self._finalize("error")

                self._log("info", f"Logging in as @{username}...")
                success = await platform_session.login(username, password)
                if not success:
                    self._log("error", f"Login failed for @{username}")
                    self.state = AgentState.ERROR
                    return self._finalize("error")

                self._log("success", f"Logged in as @{username}")
                await self.browser.save_state(platform)
            else:
                self._log("info", "Already logged in (using saved session)")

            # Build system prompt for dynamic mode
            system_prompt = build_system_prompt(campaign) if mode == "dynamic" else ""

            # Process leads
            for i, lead in enumerate(leads):
                if self._stop_requested:
                    self._log("info", "Stop requested -- halting after current lead")
                    break

                if self.stats.messages_sent >= session_limit:
                    self._log("info", f"Session limit reached ({session_limit})")
                    break

                today_count = self.store.get_today_message_count()
                if today_count >= daily_limit:
                    self._log("info", f"Daily limit reached ({daily_limit})")
                    break

                lead_name = lead.get("name", "Unknown")
                handle = lead.get("instagram_handle", "")

                if not handle and platform == "instagram":
                    self._log("warning", f"No Instagram handle for '{lead_name}' -- skipping")
                    self.stats.leads_processed += 1
                    continue

                self._log("info", f"Processing lead {i + 1}/{len(leads)}: {lead_name} (@{handle})")

                try:
                    # Generate message
                    if mode == "static":
                        message = self._generate_static(lead, campaign)
                    else:
                        message = await self._generate_dynamic(
                            lead, campaign, system_prompt, platform_session
                        )

                    if not message:
                        self._log("warning", f"Empty message for '{lead_name}' -- skipping")
                        self.stats.leads_processed += 1
                        continue

                    # Execute outreach
                    self.state = AgentState.EXECUTING
                    self._log("info", f"Sending message to @{handle} ({len(message)} chars)...")

                    success = await platform_session.send_dm(handle, message)

                    if success:
                        self.stats.messages_sent += 1
                        self.store.record_outreach(lead, "sent", message, campaign_id=campaign_id)
                        self._log("success", f"Message sent to @{handle}")
                        await self.browser.save_state(platform)
                    else:
                        self.stats.messages_failed += 1
                        self.store.record_outreach(lead, "failed", message, campaign_id=campaign_id)
                        self._log("error", f"Failed to send message to @{handle}")

                    # Human-like delay
                    self.state = AgentState.WAITING
                    delay = random.randint(delay_min, delay_max)
                    self._log("info", f"Waiting {delay}s before next message...")
                    await asyncio.sleep(delay)

                except Exception as e:
                    self.state = AgentState.ERROR
                    logger.error("Error processing lead %s: %s", lead_name, e)
                    self.stats.messages_failed += 1
                    self.store.record_outreach(lead, "failed", error=str(e), campaign_id=campaign_id)
                    self._log("error", f"Error processing '{lead_name}': {e}")

                self.stats.leads_processed += 1

        except Exception as e:
            logger.error("Fatal agent error: %s", e)
            self._log("error", f"Fatal error: {e}")
            self.state = AgentState.ERROR

        finally:
            # Clean up browser
            try:
                await self.browser.close(platform)
            except Exception:
                pass

        return self._finalize("completed" if not self._stop_requested else "stopped")

    def stop(self) -> None:
        """Request the agent to stop after the current lead."""
        self._stop_requested = True
        self._log("info", "Stop requested...")

    # ------------------------------------------------------------------
    # Message generation
    # ------------------------------------------------------------------

    def _generate_static(self, lead: dict[str, Any], campaign: dict[str, Any]) -> str | None:
        """Generate a message using static template substitution."""
        template = campaign.get("message_template", "")
        if not template:
            self._log("warning", "No message template configured for static mode")
            return None

        message = build_static_message(template, lead)
        if not message.strip():
            return None

        self._log("info", f"Static message generated ({len(message)} chars)")
        return message

    async def _generate_dynamic(
        self,
        lead: dict[str, Any],
        campaign: dict[str, Any],
        system_prompt: str,
        platform_session: Any,
    ) -> str | None:
        """Generate a message using the LLM with optional scraped profile context."""
        scraped_profile = None

        # Try to get cached profile first
        lead_id = lead.get("id")
        if lead_id:
            scraped_profile = self.store.get_lead_cached_profile(lead_id)

        # Scrape fresh if needed
        if scraped_profile is None:
            handle = lead.get("instagram_handle", "")
            if handle:
                self.state = AgentState.SCRAPING
                self._log("info", f"Scraping profile @{handle} for context...")
                try:
                    scraped_profile = await platform_session.scrape_profile(handle)
                    if scraped_profile and lead_id:
                        self.store.update_lead_profile(lead_id, scraped_profile)
                        self._log("info", f"Profile scraped: {len(scraped_profile)} data points")
                except Exception as e:
                    self._log("warning", f"Profile scrape failed: {e}")

        # Build prompt
        self.state = AgentState.PLANNING
        user_prompt = build_dynamic_prompt(lead, scraped_profile)

        self._log("info", "Generating message with LLM...")
        try:
            response = await self.llm.generate(user_prompt, system=system_prompt)
        except Exception as e:
            self._log("error", f"LLM generation failed: {e}")
            return None

        if not response or not response.strip():
            return None

        # Clean response -- remove any thinking tags qwen might add
        message = response.strip()
        # Remove <think>...</think> blocks
        import re
        message = re.sub(r"<think>.*?</think>", "", message, flags=re.DOTALL).strip()
        # Remove surrounding quotes if present
        if (message.startswith('"') and message.endswith('"')) or \
           (message.startswith("'") and message.endswith("'")):
            message = message[1:-1].strip()

        self._log("info", f"LLM message generated ({len(message)} chars)")
        return message

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, level: str, message: str) -> None:
        """Write to both Python logger and the activity log DB."""
        log_fn = getattr(logger, level if level != "success" else "info", logger.info)
        log_fn(message)

        try:
            self.store.log_activity(
                message=message,
                level=level,
                campaign_id=self._campaign.get("id") if self._campaign else None,
                session_id=self._session_id,
            )
        except Exception:
            pass  # Don't let logging errors crash the agent

    def _finalize(self, status: str) -> AgentStats:
        """End the session and return stats."""
        self.state = AgentState.STOPPED
        self._log(
            "info",
            f"Agent finished -- Sent: {self.stats.messages_sent}, "
            f"Failed: {self.stats.messages_failed}, "
            f"Processed: {self.stats.leads_processed}",
        )

        if self._session_id:
            self.store.end_session(self._session_id, {
                "messages_sent": self.stats.messages_sent,
                "messages_failed": self.stats.messages_failed,
                "leads_processed": self.stats.leads_processed,
                "status": status,
            })

        return self.stats
