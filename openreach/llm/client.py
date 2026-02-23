"""Ollama LLM client wrapper."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    """Async client for the Ollama local LLM API."""

    def __init__(
        self,
        model: str = "qwen3:4b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    async def generate(self, prompt: str, system: str | None = None) -> str:
        """Generate a response from the LLM.

        Args:
            prompt: The user prompt
            system: Optional system prompt

        Returns:
            The generated text response
        """
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
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("message", {}).get("content", "")
                logger.debug("LLM response (%d chars): %s...", len(content), content[:100])
                return content

        except httpx.ConnectError:
            logger.error(
                "Cannot connect to Ollama at %s. Is Ollama running? "
                "Start it with: ollama serve",
                self.base_url,
            )
            raise
        except httpx.HTTPStatusError as e:
            logger.error("Ollama API error: %s", e)
            raise

    async def check_health(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Check if Ollama is running
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()

                # Check if model is pulled
                models = [m.get("name", "") for m in data.get("models", [])]
                model_available = any(self.model in m for m in models)

                if not model_available:
                    logger.warning(
                        "Model '%s' not found. Available: %s. "
                        "Pull it with: ollama pull %s",
                        self.model,
                        ", ".join(models) or "(none)",
                        self.model,
                    )
                    return False

                return True

        except httpx.ConnectError:
            logger.error("Ollama is not running at %s", self.base_url)
            return False
