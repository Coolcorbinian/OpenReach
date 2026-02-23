"""Playwright browser session management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".openreach" / "browser_state"


class BrowserSession:
    """Manages a persistent Playwright browser session with login state."""

    def __init__(self, headless: bool = False, slow_mo: int = 50) -> None:
        self.headless = headless
        self.slow_mo = slow_mo
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def launch(self) -> Page:
        """Launch the browser and return the main page."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = STATE_DIR / "instagram_state.json"

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
        )

        # Load saved state if available (preserves login cookies)
        if state_file.exists():
            self._context = await self._browser.new_context(
                storage_state=str(state_file),
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
        else:
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )

        self._page = await self._context.new_page()
        logger.info("Browser launched (headless=%s)", self.headless)
        return self._page

    async def save_state(self) -> None:
        """Save browser state (cookies, localStorage) for session persistence."""
        if self._context:
            state_file = STATE_DIR / "instagram_state.json"
            await self._context.storage_state(path=str(state_file))
            logger.info("Browser state saved")

    async def close(self) -> None:
        """Save state and close the browser."""
        await self.save_state()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")

    async def send_instagram_dm(self, handle: str, message: str) -> bool:
        """Send a direct message to an Instagram user.

        Args:
            handle: Instagram username (without @)
            message: The message text to send

        Returns:
            True if the message was sent successfully
        """
        if not self._page:
            raise RuntimeError("Browser not launched. Call launch() first.")

        page = self._page
        handle = handle.lstrip("@")

        try:
            # Navigate to the user's DM thread
            await page.goto(f"https://www.instagram.com/direct/t/{handle}/", wait_until="networkidle")

            # Wait for message input to appear
            textarea = await page.wait_for_selector(
                'textarea[placeholder*="Message"], div[role="textbox"]',
                timeout=10000,
            )
            if not textarea:
                logger.error("Could not find message input for @%s", handle)
                return False

            # Type the message with human-like delays
            await textarea.click()
            await page.keyboard.type(message, delay=30)

            # Send the message
            await page.keyboard.press("Enter")

            # Wait for message to appear in the thread
            await page.wait_for_timeout(2000)

            # Save browser state after successful send
            await self.save_state()

            logger.info("DM sent to @%s", handle)
            return True

        except Exception as e:
            logger.error("Failed to send DM to @%s: %s", handle, e)
            return False

    @property
    def page(self) -> Page | None:
        return self._page
