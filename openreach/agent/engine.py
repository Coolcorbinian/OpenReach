"""Core agent loop -- prompt-driven LLM with browser tool-calling.

The AgentEngine coordinates:
1. Task configuration (user prompt, lead context, LLM settings)
2. Browser session management (Playwright lifecycle)
3. Tool-calling loop: LLM decides actions -> tools execute -> results fed back
4. Real-time streaming of reasoning + tool calls to the UI
5. Activity logging and agent turn recording
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from openreach.agent.tools import build_tool_registry
from openreach.browser.session import BrowserSession
from openreach.data.store import DataStore
from openreach.llm.client import LLMClient, StreamChunk, ChunkType, AgentTurn

logger = logging.getLogger(__name__)


class AgentState(Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    WAITING = "waiting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentStats:
    messages_sent: int = 0
    messages_failed: int = 0
    leads_processed: int = 0
    tool_calls_made: int = 0
    turns_used: int = 0
    session_start: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0


class AgentEngine:
    """Prompt-driven agent that controls a browser via LLM tool-calling.

    The user provides a natural-language task prompt. The LLM (via OpenRouter
    or Ollama) decides what browser actions to take by calling tools. The
    engine executes those tools and feeds results back until the LLM completes
    the task or hits the turn limit.

    Lifecycle:
        1. start() is called with a task dict
        2. Browser launches (visible to user)
        3. LLM receives system prompt + task + tools
        4. Tool-calling loop runs until completion
        5. stop() can be called externally to halt
    """

    def __init__(
        self,
        llm: LLMClient,
        browser: BrowserSession,
        store: DataStore,
        cormass_api: Any | None = None,
    ) -> None:
        self.llm = llm
        self.browser = browser
        self.store = store
        self.cormass_api = cormass_api
        self.state = AgentState.IDLE
        self.stats = AgentStats()
        self._stop_requested = False
        self._task: dict[str, Any] | None = None
        self._session_id: int | None = None
        self._on_chunk: Callable[[StreamChunk], Awaitable[None]] | None = None
        self._last_state_save: float = 0.0
        self._state_save_interval: float = 120.0  # Save browser state every 2 minutes
        self._messages_this_session: int = 0
        self._session_limit: int = 15
        self._daily_limit: int = 50

    async def start(
        self,
        campaign: dict[str, Any],
        leads: list[dict[str, Any]] | None = None,
        on_chunk: Callable[[StreamChunk], Awaitable[None]] | None = None,
    ) -> AgentStats:
        """Run the agent with a task definition.

        Args:
            campaign: Task/campaign dict from the database (has user_prompt, etc.)
            leads: Optional list of leads (for backward compat / pre-loaded leads)
            on_chunk: Async callback for real-time streaming to UI

        Returns:
            AgentStats with final counts
        """
        self._task = campaign
        self._on_chunk = on_chunk
        self.state = AgentState.STARTING
        self.stats = AgentStats()
        self.stats.session_start = time.time()
        self._stop_requested = False
        self._last_state_save = time.time()
        self._messages_this_session = 0
        self._session_limit = campaign.get("session_limit", 15)
        self._daily_limit = campaign.get("daily_limit", 50)

        task_id = campaign.get("id")
        user_prompt = campaign.get("user_prompt", "").strip()

        if not user_prompt:
            self._log("error", "No task prompt provided. Cannot start agent.")
            self.state = AgentState.ERROR
            return self._finalize("error")

        # Start a DB session
        self._session_id = self.store.start_session()
        self._log("info", f"Agent starting -- task: {campaign.get('name', 'Unnamed')}")

        try:
            # Launch browser
            self._log("info", "Launching browser...")
            page = await self.browser.launch(platform="general")
            self._log("info", "Browser ready")

            # Item 6: Check for saved login cookies before running
            await self._check_login_state(page)

            # Build tool registry
            tools = build_tool_registry(
                page=page,
                cormass_api=self.cormass_api,
                store=self.store,
                task_id=task_id,
                stop_callback=self.stop,
                engine=self,
            )
            self._log("info", f"Loaded {len(tools)} tools for the agent")

            # Build system prompt
            from openreach.llm.prompts import build_agent_system_prompt
            system_prompt = build_agent_system_prompt(campaign, leads)

            # Build user message (the task)
            user_message = self._build_user_message(campaign, leads)

            # Run the LLM tool-calling loop
            self.state = AgentState.RUNNING

            async def _on_chunk_wrapper(chunk: StreamChunk) -> None:
                """Forward chunks to UI callback and log to DB."""
                # Forward to UI
                if self._on_chunk:
                    await self._on_chunk(chunk)

                # Track stats
                if chunk.type == ChunkType.TOOL_CALL:
                    self.stats.tool_calls_made += 1
                if chunk.type == ChunkType.DONE:
                    self.stats.turns_used = chunk.turn_number
                # Track cumulative tokens and cost (Item 9)
                if chunk.tokens_used:
                    self.stats.total_tokens = chunk.tokens_used
                if chunk.cost:
                    self.stats.total_cost = chunk.cost

                # Log errors from LLM client to activity feed so users see them
                if chunk.type == ChunkType.ERROR:
                    self._log("error", f"LLM: {chunk.content}")

                # Periodic browser state saving (Item 10)
                now = time.time()
                if now - self._last_state_save >= self._state_save_interval:
                    try:
                        await self.browser.save_state("general")
                        self._last_state_save = now
                        logger.debug("Periodic browser state save completed")
                    except Exception:
                        pass

                # Check stop
                if self._stop_requested:
                    raise asyncio.CancelledError("Stop requested")

            try:
                turns = await self.llm.run_agent(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    tools=tools,
                    on_chunk=_on_chunk_wrapper,
                )
            except asyncio.CancelledError:
                self._log("info", "Agent stopped by user request")
                turns = []

            # Record turns to DB
            for turn in turns:
                try:
                    self.store.log_agent_turn(
                        campaign_id=task_id,
                        session_id=self._session_id,
                        turn_number=turn.turn_number,
                        role=turn.role,
                        content=turn.content,
                        tool_name=turn.tool_name,
                        tool_args=turn.tool_args,
                        tool_result=turn.tool_result,
                        tokens_used=turn.tokens_used,
                    )
                except Exception:
                    pass

            self.stats.turns_used = len(turns)
            self._log("info", f"Agent completed: {self.stats.turns_used} turns, {self.stats.tool_calls_made} tool calls")

        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Fatal agent error: %s\n%s", e, tb)
            self._log("error", f"Fatal error: {e}")
            self.state = AgentState.ERROR

        finally:
            try:
                await self.browser.close("general")
            except Exception:
                pass

        return self._finalize("completed" if not self._stop_requested else "stopped")

    def stop(self) -> None:
        """Request the agent to stop after the current tool call."""
        self._stop_requested = True
        self._log("info", "Stop requested...")

    # ------------------------------------------------------------------
    # Login / cookie detection (Item 6)
    # ------------------------------------------------------------------

    async def _check_login_state(self, page: Any) -> None:
        """Check if the browser has saved login cookies for common platforms."""
        try:
            context = page.context
            cookies = await context.cookies()
            # Check for Instagram session cookie
            ig_session = any(
                c.get("name") == "sessionid" and "instagram" in c.get("domain", "")
                for c in cookies
            )
            if ig_session:
                self._log("info", "Instagram login detected (session cookie found)")
            else:
                self._log("warning",
                    "No Instagram session cookie found. The agent may need to log in manually. "
                    "For best results, log into Instagram in the browser first and save the state."
                )
        except Exception as e:
            logger.debug("Cookie check failed: %s", e)

    # ------------------------------------------------------------------
    # Rate limiting (Item 11)
    # ------------------------------------------------------------------

    def check_rate_limits(self) -> tuple[bool, str]:
        """Check if rate limits allow sending another message.

        Returns:
            (allowed, reason) tuple
        """
        # Session limit
        if self._messages_this_session >= self._session_limit:
            return False, f"Session limit reached ({self._session_limit} messages)"

        # Daily limit
        try:
            today_count = self.store.get_today_message_count()
            if today_count >= self._daily_limit:
                return False, f"Daily limit reached ({self._daily_limit} messages)"
        except Exception:
            pass

        return True, ""

    def increment_message_count(self, success: bool = True) -> None:
        """Increment message counters (called by log_message_sent tool)."""
        if success:
            self.stats.messages_sent += 1
            self._messages_this_session += 1
        else:
            self.stats.messages_failed += 1

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------

    def _build_user_message(self, campaign: dict[str, Any], leads: list[dict[str, Any]] | None) -> str:
        """Build the user message for the LLM from the task prompt and lead context."""
        parts: list[str] = []

        user_prompt = campaign.get("user_prompt", "")
        parts.append(f"## Task\n{user_prompt}")

        additional = campaign.get("additional_notes", "").strip()
        if additional:
            parts.append(f"\n## Additional Context\n{additional}")

        # Lead data summary
        if leads:
            parts.append(f"\n## Leads ({len(leads)} total)")
            for i, lead in enumerate(leads[:20]):
                name = lead.get("name", "Unknown")
                btype = lead.get("business_type", "")
                loc = lead.get("location", "")
                handle = lead.get("instagram_handle", "")
                phone = lead.get("phone_number", "")
                email = lead.get("email", "")
                website = lead.get("website", "")

                line = f"{i+1}. **{name}**"
                if btype:
                    line += f" ({btype})"
                if loc:
                    line += f" - {loc[:50]}"
                details = []
                if handle:
                    details.append(f"IG: @{handle}")
                if phone:
                    details.append(f"Tel: {phone}")
                if email:
                    details.append(f"Email: {email}")
                if website:
                    details.append(f"Web: {website}")
                if details:
                    line += " | " + ", ".join(details)
                parts.append(line)

            if len(leads) > 20:
                parts.append(f"... and {len(leads) - 20} more leads (use leads_get_canvas to view all)")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, level: str, message: str) -> None:
        """Write to both Python logger and the activity log DB."""
        log_fn = getattr(logger, level if level not in ("success", "debug") else ("info" if level == "success" else "debug"), logger.info)
        log_fn(message)

        try:
            self.store.log_activity(
                message=message,
                level=level,
                campaign_id=self._task.get("id") if self._task else None,
                session_id=self._session_id,
            )
        except Exception:
            pass

    def _finalize(self, status: str) -> AgentStats:
        """End the session and return stats."""
        self.state = AgentState.STOPPED
        self._log(
            "info",
            f"Agent finished -- Turns: {self.stats.turns_used}, "
            f"Tool calls: {self.stats.tool_calls_made}",
        )

        if self._session_id:
            self.store.end_session(self._session_id, {
                "messages_sent": self.stats.tool_calls_made,
                "messages_failed": self.stats.messages_failed,
                "leads_processed": self.stats.leads_processed,
                "status": status,
            })

        return self.stats
