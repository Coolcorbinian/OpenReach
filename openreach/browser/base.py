"""Abstract base class for platform-specific browser sessions."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)


class PlatformSession(ABC):
    """Abstract interface that every platform-specific session must implement."""

    @abstractmethod
    async def login(self, username: str, password: str) -> bool:
        """Log in to the platform. Returns True on success."""
        ...

    @abstractmethod
    async def is_logged_in(self) -> bool:
        """Check if the session is currently authenticated."""
        ...

    @abstractmethod
    async def send_dm(self, handle: str, message: str) -> bool:
        """Send a direct message to the given handle. Returns True on success."""
        ...

    @abstractmethod
    async def scrape_profile(self, handle: str) -> dict[str, Any] | None:
        """Scrape the public profile of the given handle. Returns profile dict or None."""
        ...

    @abstractmethod
    async def navigate_to_profile(self, handle: str) -> bool:
        """Navigate the browser to the profile page. Returns True on success."""
        ...
