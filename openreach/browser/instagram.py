"""Instagram-specific browser automation using Playwright.

Handles:
- Login with username/password
- Cookie/notification popup dismissal
- Profile-first DM navigation (instagram.com/{handle} -> Message button)
- Profile scraping for dynamic outreach context
- State persistence between sessions
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from openreach.browser.base import PlatformSession

logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".openreach" / "browser_state"


class InstagramSession(PlatformSession):
    """Instagram platform automation."""

    def __init__(self, page: Page) -> None:
        self._page = page

    # ------------------------------------------------------------------
    # Popup handling
    # ------------------------------------------------------------------

    async def dismiss_popups(self) -> None:
        """Dismiss common Instagram popups (cookies, notifications, etc.)."""
        page = self._page
        logger.debug("dismiss_popups() called -- current URL: %s", page.url)

        # Cookie consent -- "Allow all cookies" or "Decline optional cookies"
        for selector in [
            'button:has-text("Allow all cookies")',
            'button:has-text("Allow essential and optional cookies")',
            'button:has-text("Decline optional cookies")',
            'button:has-text("Accept All")',
            'button:has-text("Accept")',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await asyncio.sleep(0.5)
                    logger.debug("Dismissed cookie popup via: %s", selector)
                    break
            except Exception:
                logger.debug("Cookie selector not found: %s", selector)

        # "Turn on Notifications" dialog
        for selector in [
            'button:has-text("Not Now")',
            'button:has-text("Cancel")',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await asyncio.sleep(0.5)
                    logger.debug("Dismissed notification popup via: %s", selector)
                    break
            except Exception:
                logger.debug("Notification selector not found: %s", selector)

        # "Save Your Login Info?" dialog
        try:
            btn = page.locator('button:has-text("Not Now")').first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await asyncio.sleep(0.5)
                logger.debug("Dismissed 'Save Login Info' popup")
        except Exception:
            logger.debug("No 'Save Login Info' popup found")
        
        logger.debug("dismiss_popups() complete -- URL after: %s", page.url)

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self, username: str, password: str) -> bool:
        """Log in to Instagram with username and password.

        Args:
            username: Instagram username
            password: Instagram password

        Returns:
            True if login succeeded
        """
        page = self._page

        try:
            logger.info("Navigating to Instagram login page...")
            logger.debug("page.goto('https://www.instagram.com/accounts/login/', wait_until='domcontentloaded')")
            await page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
            logger.debug("Navigation complete -- URL: %s, title: %s", page.url, await page.title())
            await asyncio.sleep(2)

            # Dismiss cookie popup first
            logger.debug("Dismissing pre-login popups...")
            await self.dismiss_popups()
            await asyncio.sleep(1)

            # Wait for login form
            logger.debug("Waiting for login form elements...")
            username_input = page.locator('input[name="username"]')
            password_input = page.locator('input[name="password"]')

            logger.debug("Waiting for username input to become visible (timeout=10s)...")
            await username_input.wait_for(state="visible", timeout=10000)
            logger.debug("Username input visible. Checking password input...")
            
            try:
                await password_input.wait_for(state="visible", timeout=5000)
                logger.debug("Password input visible.")
            except Exception as e:
                logger.debug("Password input wait failed: %s", e)

            # Clear and type credentials
            logger.debug("Clicking username input and typing credentials...")
            await username_input.click()
            await username_input.fill("")
            await page.keyboard.type(username, delay=40)
            logger.debug("Username typed (%d chars)", len(username))

            await password_input.click()
            await password_input.fill("")
            await page.keyboard.type(password, delay=40)
            logger.debug("Password typed (%d chars)", len(password))

            await asyncio.sleep(0.5)

            # Click Log In button
            logger.debug("Looking for submit button...")
            login_btn = page.locator('button[type="submit"]').first
            logger.debug("Clicking submit button...")
            await login_btn.click()
            logger.debug("Submit clicked -- waiting for navigation...")

            # Wait for navigation after login
            await asyncio.sleep(4)
            logger.debug("Post-login URL: %s", page.url)

            # Dismiss any post-login popups
            logger.debug("Dismissing post-login popups (round 1)...")
            await self.dismiss_popups()
            await asyncio.sleep(1)
            logger.debug("Dismissing post-login popups (round 2)...")
            await self.dismiss_popups()

            # Verify login by checking URL or profile elements
            current_url = page.url
            logger.debug("Verifying login -- current URL: %s", current_url)
            if "/accounts/login" in current_url or "challenge" in current_url:
                logger.error("Login may have failed -- still on login/challenge page: %s", current_url)
                # Check for specific error messages
                error_el = page.locator('#slfErrorAlert, [data-testid="login-error-message"]').first
                try:
                    if await error_el.is_visible(timeout=2000):
                        error_text = await error_el.text_content()
                        logger.error("Login error: %s", error_text)
                except Exception:
                    logger.debug("No visible error element found on login page")
                return False

            logger.info("Instagram login successful for @%s", username)
            return True

        except PlaywrightTimeout as e:
            logger.error("Login timed out: %s", e)
            logger.debug("Timeout details -- URL at timeout: %s", page.url)
            return False
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error("Login error: %s", e)
            logger.debug("Login exception traceback:\n%s", tb)
            return False

    async def is_logged_in(self) -> bool:
        """Check if we're currently logged into Instagram."""
        page = self._page
        try:
            logger.debug("is_logged_in() -- navigating to instagram.com...")
            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            logger.debug("Navigation complete -- URL: %s", page.url)
            await asyncio.sleep(2)
            logger.debug("Dismissing popups during login check...")
            await self.dismiss_popups()

            # If we're redirected to login page, we're not logged in
            if "/accounts/login" in page.url:
                logger.debug("Redirected to login page -- not logged in")
                return False

            # Look for elements that only appear when logged in
            # The navigation bar with profile icon, or the search icon
            nav_sel = 'svg[aria-label="Home"], a[href="/direct/inbox/"], svg[aria-label="Search"]'
            logger.debug("Checking for logged-in nav elements: %s", nav_sel)
            try:
                el = page.locator(nav_sel).first
                is_visible = await el.is_visible(timeout=5000)
                logger.debug("Nav element visible: %s", is_visible)
                return is_visible
            except Exception as e:
                logger.debug("Nav element check failed: %s", e)
                return False

        except Exception as e:
            import traceback
            logger.error("Error checking login status: %s", e)
            logger.debug("is_logged_in traceback:\n%s", traceback.format_exc())
            return False

    # ------------------------------------------------------------------
    # Direct Message
    # ------------------------------------------------------------------

    async def send_dm(self, handle: str, message: str) -> bool:
        """Send a DM to an Instagram user via their profile page.

        Navigation flow:
        1. Go to instagram.com/{handle}
        2. Click the "Message" button on their profile
        3. Type and send the message

        Args:
            handle: Instagram username (without @)
            message: Message text to send

        Returns:
            True if message was sent successfully
        """
        page = self._page
        handle = handle.lstrip("@")

        try:
            # Step 1: Navigate to profile
            logger.debug("send_dm() -- navigating to profile @%s", handle)
            if not await self.navigate_to_profile(handle):
                return False

            await asyncio.sleep(1)
            await self.dismiss_popups()

            # Step 2: Click Message button
            logger.debug("Looking for Message button on @%s's profile...", handle)
            msg_btn = page.locator('div[role="button"]:has-text("Message")').first
            try:
                await msg_btn.wait_for(state="visible", timeout=8000)
                logger.debug("Message button found -- clicking...")
                await msg_btn.click()
            except PlaywrightTimeout:
                logger.debug("Primary Message button selector failed, trying alternatives...")
                # Try alternative selectors
                alt_btn = page.locator('a:has-text("Message"), button:has-text("Message")').first
                try:
                    await alt_btn.wait_for(state="visible", timeout=3000)
                    logger.debug("Alternative Message button found -- clicking...")
                    await alt_btn.click()
                except Exception:
                    logger.error("Could not find Message button on @%s's profile", handle)
                    return False

            await asyncio.sleep(2)
            logger.debug("Post-Message-click URL: %s", page.url)
            await self.dismiss_popups()

            # Step 3: Find the message input
            logger.debug("Looking for message input textarea...")
            textarea = None
            for sel in [
                'div[role="textbox"][contenteditable="true"]',
                'textarea[placeholder*="Message"]',
                'div[aria-label*="Message"]',
                'p[data-lexical-text="true"]',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=3000):
                        textarea = el
                        logger.debug("Message input found via selector: %s", sel)
                        break
                except Exception:
                    logger.debug("Message input selector not matched: %s", sel)
                    continue

            if not textarea:
                logger.error("Could not find message input for @%s", handle)
                return False

            # Step 4: Type and send
            logger.debug("Typing message (%d chars)...", len(message))
            await textarea.click()
            await asyncio.sleep(0.3)
            await page.keyboard.type(message, delay=25)
            await asyncio.sleep(0.3)
            logger.debug("Pressing Enter to send...")
            await page.keyboard.press("Enter")

            # Wait for message to appear
            await asyncio.sleep(2)

            logger.info("DM sent to @%s (%d chars)", handle, len(message))
            return True

        except Exception as e:
            import traceback
            logger.error("Failed to send DM to @%s: %s", handle, e)
            logger.debug("send_dm traceback:\n%s", traceback.format_exc())
            return False

    # ------------------------------------------------------------------
    # Profile navigation
    # ------------------------------------------------------------------

    async def navigate_to_profile(self, handle: str) -> bool:
        """Navigate to a user's Instagram profile.

        Args:
            handle: Instagram username (without @)

        Returns:
            True if the profile was loaded successfully
        """
        page = self._page
        handle = handle.lstrip("@")

        try:
            logger.debug("navigate_to_profile() -- going to instagram.com/%s/", handle)
            await page.goto(
                f"https://www.instagram.com/{handle}/",
                wait_until="domcontentloaded",
            )
            logger.debug("Profile navigation complete -- URL: %s", page.url)
            await asyncio.sleep(2)
            await self.dismiss_popups()

            # Check if profile exists (not a 404)
            page_content = await page.content()
            if "Sorry, this page isn't available" in page_content:
                logger.warning("Profile @%s not found (404)", handle)
                return False

            # Wait for profile header to load
            logger.debug("Waiting for profile header section...")
            try:
                header = page.locator('header section').first
                await header.wait_for(state="visible", timeout=8000)
                logger.debug("Profile header loaded for @%s", handle)
            except PlaywrightTimeout:
                logger.warning("Profile page for @%s did not load properly", handle)
                logger.debug("Current URL: %s, page title: %s", page.url, await page.title())
                return False

            return True

        except Exception as e:
            import traceback
            logger.error("Error navigating to @%s: %s", handle, e)
            logger.debug("navigate_to_profile traceback:\n%s", traceback.format_exc())
            return False

    # ------------------------------------------------------------------
    # Profile scraping
    # ------------------------------------------------------------------

    async def scrape_profile(self, handle: str) -> dict[str, Any] | None:
        """Scrape public profile data from an Instagram user's page.

        Extracts: display name, bio, followers, following, post count,
        category, external URL, verified status, recent post captions.

        Args:
            handle: Instagram username (without @)

        Returns:
            Profile data dict, or None on failure
        """
        page = self._page
        handle = handle.lstrip("@")

        try:
            # Navigate to profile if not already there
            current_path = page.url.rstrip("/").split("instagram.com")[-1] if "instagram.com" in page.url else ""
            if current_path.strip("/") != handle:
                if not await self.navigate_to_profile(handle):
                    return None

            profile: dict[str, Any] = {"handle": handle}

            # Extract display name
            try:
                # Display name is usually in a span within the header
                name_el = page.locator('header section span:not([class*="coreSpriteVerifiedBadge"])').first
                name_text = await name_el.text_content(timeout=3000)
                if name_text:
                    profile["display_name"] = name_text.strip()
            except Exception:
                pass

            # Extract bio
            try:
                # Bio is in a div with specific structure
                bio_el = page.locator('header section div span, header section h1 + div span').first
                bio_text = await bio_el.text_content(timeout=3000)
                if bio_text and len(bio_text) > 1:
                    profile["bio"] = bio_text.strip()
            except Exception:
                pass

            # Extract follower/following/post counts from the stats section
            try:
                stats_items = page.locator('header section ul li, header section a[href*="followers"], header section a[href*="following"]')
                stat_texts = await stats_items.all_text_contents()

                for text in stat_texts:
                    text_lower = text.lower().strip()
                    number = self._parse_count(text_lower)
                    if "follower" in text_lower:
                        profile["followers"] = number
                    elif "following" in text_lower:
                        profile["following"] = number
                    elif "post" in text_lower:
                        profile["post_count"] = number
            except Exception:
                pass

            # Extract through meta tags as fallback
            try:
                meta_desc = await page.locator('meta[name="description"]').get_attribute("content", timeout=2000)
                if meta_desc:
                    # Typical format: "123 Followers, 456 Following, 789 Posts - See Instagram..."
                    nums = re.findall(r"([\d,.KkMm]+)\s+(Followers|Following|Posts)", meta_desc, re.IGNORECASE)
                    for val, label in nums:
                        count = self._parse_count(val)
                        if "follower" in label.lower() and "followers" not in profile:
                            profile["followers"] = count
                        elif "following" in label.lower() and "following" not in profile:
                            profile["following"] = count
                        elif "post" in label.lower() and "post_count" not in profile:
                            profile["post_count"] = count

                    # Bio from meta
                    if "bio" not in profile:
                        bio_match = re.search(r"Posts\s*[-\u2013]\s*(.+?)(?:\s*$|\s*See Instagram)", meta_desc, re.IGNORECASE)
                        if bio_match:
                            profile["bio"] = bio_match.group(1).strip().strip('"')
            except Exception:
                pass

            # Verified badge
            try:
                verified = page.locator('svg[aria-label="Verified"], span[title="Verified"]').first
                profile["is_verified"] = await verified.is_visible(timeout=2000)
            except Exception:
                profile["is_verified"] = False

            # Category label (e.g., "Restaurant", "Personal Blog")
            try:
                cat_el = page.locator('header section div[class*="category"], header div:has-text("Category")').first
                cat_text = await cat_el.text_content(timeout=2000)
                if cat_text and len(cat_text) < 60:
                    profile["category"] = cat_text.strip()
            except Exception:
                pass

            # External URL
            try:
                link_el = page.locator('header section a[rel="me nofollow noopener noreferrer"], header a[href*="l.instagram.com"]').first
                external_url = await link_el.get_attribute("href", timeout=2000)
                if external_url:
                    profile["external_url"] = external_url
            except Exception:
                pass

            # Recent post captions (first 3-5 visible)
            try:
                # Scroll down slightly to load posts
                await page.evaluate("window.scrollBy(0, 400)")
                await asyncio.sleep(1)

                # Instagram article elements
                articles = page.locator('article img[alt]')
                alt_texts = await articles.all_text_contents()[:5]
                if not alt_texts:
                    # Try getting alt attributes instead
                    imgs = await articles.all()
                    alt_texts = []
                    for img in imgs[:5]:
                        alt = await img.get_attribute("alt")
                        if alt and len(alt) > 10:
                            alt_texts.append(alt)

                if alt_texts:
                    profile["recent_posts"] = alt_texts
            except Exception:
                pass

            logger.info("Scraped profile @%s: %d data points", handle, len(profile))
            return profile if len(profile) > 1 else None

        except Exception as e:
            logger.error("Failed to scrape profile @%s: %s", handle, e)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_count(text: str) -> int:
        """Parse a follower/post count string like '12.3K', '1.2M', '1,234'."""
        text = text.strip().replace(",", "").replace(" ", "")
        # Extract the numeric part
        match = re.search(r"([\d.]+)\s*([kmb])?", text, re.IGNORECASE)
        if not match:
            return 0
        num = float(match.group(1))
        suffix = (match.group(2) or "").lower()
        multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
        return int(num * multipliers.get(suffix, 1))
