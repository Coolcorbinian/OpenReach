"""Playwright browser session management.

This module manages the Playwright browser lifecycle and provides
platform-specific session instances through a factory pattern.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from openreach.browser.base import PlatformSession

logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".openreach" / "browser_state"


class BrowserSession:
    """Manages a persistent Playwright browser session with login state."""

    def __init__(self, config: dict | None = None, headless: bool = False, slow_mo: int = 50) -> None:
        if config and isinstance(config, dict):
            browser_cfg = config.get("browser", {})
            self.headless = browser_cfg.get("headless", headless)
            self.slow_mo = browser_cfg.get("slow_mo", slow_mo)
        else:
            self.headless = headless
            self.slow_mo = slow_mo
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def launch(self, platform: str = "instagram") -> Page:
        """Launch the browser and return the main page.

        Args:
            platform: The platform to load saved state for (default: instagram)

        Returns:
            The Playwright Page object
        """
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = STATE_DIR / f"{platform}_state.json"

        logger.debug("Starting Playwright async instance...")
        self._playwright = await async_playwright().start()
        logger.debug("Playwright started. Launching Chromium (headless=%s, slow_mo=%s)...", self.headless, self.slow_mo)
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
        )
        logger.debug("Chromium browser process launched (pid=%s)", getattr(self._browser, '_impl_obj', {}) )

        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

        # Load saved state if available (preserves login cookies)
        if state_file.exists():
            logger.debug("Loading saved browser state from %s", state_file)
            self._context = await self._browser.new_context(
                storage_state=str(state_file),
                viewport={"width": 1280, "height": 800},
                user_agent=ua,
            )
        else:
            logger.debug("No saved state found at %s -- creating fresh context", state_file)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=ua,
            )

        logger.debug("Browser context created. Opening new page...")
        self._page = await self._context.new_page()
        logger.info("Browser launched (headless=%s, platform=%s)", self.headless, platform)
        logger.debug("Page ready: %s", self._page.url)
        return self._page

    def get_platform_session(self, platform: str) -> PlatformSession:
        """Get a platform-specific session instance.

        Args:
            platform: Platform name (instagram, linkedin, twitter, email)

        Returns:
            A PlatformSession implementation

        Raises:
            ValueError: If platform is unsupported
            RuntimeError: If browser not launched
        """
        if not self._page:
            raise RuntimeError("Browser not launched. Call launch() first.")

        if platform == "instagram":
            from openreach.browser.instagram import InstagramSession
            return InstagramSession(self._page)
        else:
            raise ValueError(
                f"Unsupported platform: {platform}. "
                f"Currently supported: instagram"
            )

    async def save_state(self, platform: str = "instagram") -> None:
        """Save browser state (cookies, localStorage) for session persistence."""
        if self._context:
            state_file = STATE_DIR / f"{platform}_state.json"
            await self._context.storage_state(path=str(state_file))
            logger.info("Browser state saved for %s", platform)

    async def close(self, platform: str = "instagram") -> None:
        """Save state and close the browser."""
        await self.save_state(platform)
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Browser closed")

    # Legacy method for backward compatibility
    async def send_instagram_dm(self, handle: str, message: str) -> bool:
        """Send a DM via Instagram (legacy wrapper)."""
        session = self.get_platform_session("instagram")
        return await session.send_dm(handle, message)

    @property
    def page(self) -> Page | None:
        return self._page
