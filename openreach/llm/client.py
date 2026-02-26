"""Multi-provider LLM client with tool-calling support.

Supports two backends:
  - OpenRouter (default): Cloud API with full tool-calling, streaming, Qwen 3 access
  - Ollama (legacy): Local inference, text-only (no tool-calling), offline capable

The client implements an agentic tool-calling loop: it sends messages + tool
definitions to the LLM, executes any tool calls returned, feeds results back,
and repeats until the LLM produces a final text response or hits the turn limit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Awaitable

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider enum
# ---------------------------------------------------------------------------

class LLMProvider(Enum):
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"


# ---------------------------------------------------------------------------
# Streaming event types
# ---------------------------------------------------------------------------

class ChunkType(Enum):
    REASONING = "reasoning"
    CONTENT = "content"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    DONE = "done"


@dataclass
class StreamChunk:
    """A single chunk from the LLM stream."""
    type: ChunkType
    content: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_call_id: str | None = None
    turn_number: int = 0


# ---------------------------------------------------------------------------
# Tool definition helper
# ---------------------------------------------------------------------------

@dataclass
class ToolDef:
    """A tool definition for the LLM."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[..., Awaitable[str]]  # async function to execute

    def to_openrouter_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------------------------------------------------------------------------
# Turn record (for conversation history / UI display)
# ---------------------------------------------------------------------------

@dataclass
class AgentTurn:
    """Record of a single turn in the agent conversation."""
    turn_number: int
    role: str  # "assistant", "tool"
    content: str = ""
    tool_name: str | None = None
    tool_args: str | None = None  # JSON string
    tool_result: str | None = None
    tokens_used: int = 0
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class LLMClient:
    """Multi-provider LLM client with agentic tool-calling loop.

    Usage:
        client = LLMClient(provider="openrouter", api_key="sk-...", model="qwen/qwen3-235b-a22b")
        tools = [ToolDef(name="browser_navigate", ...)]

        # Streaming tool-calling loop
        turns = await client.run_agent(system_prompt, user_message, tools, on_chunk=callback)

        # Simple one-shot (no tools, no streaming)
        text = await client.generate("Write a greeting", system="You are helpful.")
    """

    def __init__(
        self,
        provider: str = "openrouter",
        api_key: str = "",
        model: str = "qwen/qwen3-235b-a22b",
        base_url: str = "",
        temperature: float = 0.4,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        max_turns: int = 50,
    ) -> None:
        self.provider = LLMProvider(provider)
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_turns = max_turns

        if self.provider == LLMProvider.OPENROUTER:
            self.base_url = base_url or "https://openrouter.ai/api/v1"
        else:
            self.base_url = (base_url or "http://localhost:11434").rstrip("/")

    # ------------------------------------------------------------------
    # Agentic tool-calling loop (primary interface)
    # ------------------------------------------------------------------

    async def run_agent(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolDef] | None = None,
        on_chunk: Callable[[StreamChunk], Awaitable[None]] | None = None,
    ) -> list[AgentTurn]:
        """Run the full agentic loop with tool-calling.

        Sends the initial messages + tools to the LLM. If the LLM returns
        tool_calls, executes them, feeds results back, and continues until
        the LLM produces a final text response or max_turns is reached.

        Args:
            system_prompt: System message defining agent behavior
            user_message: The user's task/instruction
            tools: List of available tool definitions
            on_chunk: Optional async callback for streaming chunks to UI

        Returns:
            List of AgentTurn records for the full conversation
        """
        if self.provider == LLMProvider.OLLAMA:
            return await self._run_agent_ollama(system_prompt, user_message, on_chunk)

        return await self._run_agent_openrouter(system_prompt, user_message, tools, on_chunk)

    async def _run_agent_openrouter(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolDef] | None,
        on_chunk: Callable[[StreamChunk], Awaitable[None]] | None,
    ) -> list[AgentTurn]:
        """OpenRouter agentic loop with real tool-calling."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        tool_schemas = [t.to_openrouter_schema() for t in tools] if tools else None
        tool_map = {t.name: t for t in tools} if tools else {}
        turns: list[AgentTurn] = []
        turn_number = 0

        async with httpx.AsyncClient(timeout=self.timeout) as http:
            while turn_number < self.max_turns:
                turn_number += 1

                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "stream": False,
                }
                if tool_schemas:
                    payload["tools"] = tool_schemas
                    payload["tool_choice"] = "auto"

                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://openreach.app",
                    "X-Title": "OpenReach Agent",
                }

                # --- Send request ---
                try:
                    resp = await http.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPStatusError as e:
                    error_msg = f"OpenRouter API error: {e.response.status_code} - {e.response.text[:500]}"
                    logger.error(error_msg)
                    if on_chunk:
                        await on_chunk(StreamChunk(type=ChunkType.ERROR, content=error_msg, turn_number=turn_number))
                    turns.append(AgentTurn(turn_number=turn_number, role="error", content=error_msg))
                    break
                except httpx.ConnectError as e:
                    error_msg = f"Cannot connect to OpenRouter: {e}"
                    logger.error(error_msg)
                    if on_chunk:
                        await on_chunk(StreamChunk(type=ChunkType.ERROR, content=error_msg, turn_number=turn_number))
                    turns.append(AgentTurn(turn_number=turn_number, role="error", content=error_msg))
                    break

                # --- Parse response ---
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                finish_reason = choice.get("finish_reason", "")
                usage = data.get("usage", {})
                tokens = usage.get("total_tokens", 0)

                content = message.get("content") or ""
                tool_calls = message.get("tool_calls") or []

                # Append assistant message to conversation
                messages.append(message)

                # --- Emit reasoning/content ---
                if content:
                    turn = AgentTurn(
                        turn_number=turn_number,
                        role="assistant",
                        content=content,
                        tokens_used=tokens,
                    )
                    turns.append(turn)
                    if on_chunk:
                        await on_chunk(StreamChunk(
                            type=ChunkType.CONTENT if not tool_calls else ChunkType.REASONING,
                            content=content,
                            turn_number=turn_number,
                        ))

                # --- Handle tool calls ---
                if tool_calls:
                    for tc in tool_calls:
                        tc_id = tc.get("id", "")
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args_str = fn.get("arguments", "{}")

                        try:
                            fn_args = json.loads(fn_args_str) if isinstance(fn_args_str, str) else fn_args_str
                        except json.JSONDecodeError:
                            fn_args = {}

                        # Emit tool call chunk
                        if on_chunk:
                            await on_chunk(StreamChunk(
                                type=ChunkType.TOOL_CALL,
                                content=f"Calling {fn_name}",
                                tool_name=fn_name,
                                tool_args=fn_args,
                                tool_call_id=tc_id,
                                turn_number=turn_number,
                            ))

                        # Execute tool
                        tool_result = ""
                        tool_def = tool_map.get(fn_name)
                        if tool_def:
                            try:
                                tool_result = await tool_def.handler(**fn_args)
                            except Exception as e:
                                tool_result = f"Error executing {fn_name}: {e}"
                                logger.error("Tool %s failed: %s", fn_name, e)
                        else:
                            tool_result = f"Unknown tool: {fn_name}"
                            logger.warning("LLM called unknown tool: %s", fn_name)

                        # Truncate very long results
                        if len(tool_result) > 8000:
                            tool_result = tool_result[:8000] + "\n... [truncated]"

                        # Emit tool result chunk
                        if on_chunk:
                            await on_chunk(StreamChunk(
                                type=ChunkType.TOOL_RESULT,
                                content=tool_result[:500],
                                tool_name=fn_name,
                                tool_call_id=tc_id,
                                turn_number=turn_number,
                            ))

                        # Record turn
                        turns.append(AgentTurn(
                            turn_number=turn_number,
                            role="tool",
                            tool_name=fn_name,
                            tool_args=json.dumps(fn_args),
                            tool_result=tool_result[:2000],
                        ))

                        # Append tool result to messages
                        messages.append({
                            "role": "tool",
                            "content": tool_result,
                            "tool_call_id": tc_id,
                        })

                    # Continue loop -- LLM needs to process tool results
                    continue

                # --- No tool calls = final response ---
                if not tool_calls:
                    if not content:
                        turns.append(AgentTurn(
                            turn_number=turn_number,
                            role="assistant",
                            content="[empty response]",
                            tokens_used=tokens,
                        ))
                    if on_chunk:
                        await on_chunk(StreamChunk(type=ChunkType.DONE, turn_number=turn_number))
                    break

        return turns

    async def _run_agent_ollama(
        self,
        system_prompt: str,
        user_message: str,
        on_chunk: Callable[[StreamChunk], Awaitable[None]] | None,
    ) -> list[AgentTurn]:
        """Ollama fallback -- no tool-calling, single text generation."""
        content = await self.generate(user_message, system=system_prompt)
        turn = AgentTurn(turn_number=1, role="assistant", content=content)

        if on_chunk:
            await on_chunk(StreamChunk(type=ChunkType.CONTENT, content=content, turn_number=1))
            await on_chunk(StreamChunk(type=ChunkType.DONE, turn_number=1))

        return [turn]

    # ------------------------------------------------------------------
    # Simple one-shot generation (backward compatible)
    # ------------------------------------------------------------------

    async def generate(self, prompt: str, system: str | None = None) -> str:
        """Generate a single text response (no tools, no streaming).

        Compatible with both OpenRouter and Ollama.
        """
        if self.provider == LLMProvider.OPENROUTER:
            return await self._generate_openrouter(prompt, system)
        else:
            return await self._generate_ollama(prompt, system)

    async def _generate_openrouter(self, prompt: str, system: str | None = None) -> str:
        """One-shot generation via OpenRouter."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://openreach.app",
            "X-Title": "OpenReach Agent",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content.strip()

    async def _generate_ollama(self, prompt: str, system: str | None = None) -> str:
        """One-shot generation via local Ollama."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
            "think": False,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            logger.debug("Ollama response (%d chars)", len(content))
            return content.strip()

    def generate_sync(self, prompt: str, system: str | None = None) -> str:
        """Synchronous one-shot generation (for use outside async contexts)."""
        if self.provider == LLMProvider.OPENROUTER:
            return self._generate_openrouter_sync(prompt, system)
        else:
            return self._generate_ollama_sync(prompt, system)

    def _generate_openrouter_sync(self, prompt: str, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://openreach.app",
            "X-Title": "OpenReach Agent",
        }

        with httpx.Client(timeout=self.timeout) as http:
            resp = http.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    def _generate_ollama_sync(self, prompt: str, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
            "think": False,
        }

        with httpx.Client(timeout=self.timeout) as http:
            resp = http.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def check_health(self) -> bool:
        """Check if the LLM backend is accessible."""
        if self.provider == LLMProvider.OPENROUTER:
            return await self._check_openrouter_health()
        else:
            return await self._check_ollama_health()

    async def _check_openrouter_health(self) -> bool:
        """Verify OpenRouter API key works."""
        if not self.api_key:
            logger.warning("No OpenRouter API key configured")
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("OpenRouter health check failed: %s", e)
            return False

    async def _check_ollama_health(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                available = any(self.model in m for m in models)
                if not available:
                    logger.warning(
                        "Ollama model '%s' not found. Available: %s",
                        self.model, ", ".join(models) or "(none)",
                    )
                return available
        except httpx.ConnectError:
            logger.error("Ollama is not running at %s", self.base_url)
            return False


# ---------------------------------------------------------------------------
# Legacy alias for backward compatibility
# ---------------------------------------------------------------------------

OllamaClient = LLMClient
