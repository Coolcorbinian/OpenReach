"""Tool definitions for the OpenReach agent.

Each tool is defined as a ToolDef with:
  - name: Unique identifier for the LLM to call
  - description: What the tool does (shown to the LLM)
  - parameters: JSON Schema for the arguments
  - handler: Async Python function that executes the tool

Tool categories:
  1. Browser tools -- Playwright page interaction
  2. Data tools -- Cormass Leads API queries
  3. Utility tools -- Logging, delays, status updates
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

from playwright.async_api import Page

from openreach.llm.client import ToolDef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool registry builder
# ---------------------------------------------------------------------------

def build_tool_registry(
    page: Page | None,
    cormass_api: Any | None,
    store: Any | None,
    task_id: int | None = None,
    stop_callback: Any | None = None,
    engine: Any | None = None,
) -> list[ToolDef]:
    """Build the full list of tools available to the agent.

    Args:
        page: Playwright Page object for browser tools (None = browser tools disabled)
        cormass_api: CormassApiClient instance (None = data tools disabled)
        store: DataStore instance (None = utility store tools disabled)
        task_id: Current task ID for logging context
        stop_callback: Callable to signal the engine to stop (used by finish_task)
        engine: AgentEngine reference for message counting and rate limits

    Returns:
        List of ToolDef objects ready for LLMClient.run_agent()
    """
    tools: list[ToolDef] = []

    # --- Browser tools ---
    if page is not None:
        tools.extend(_browser_tools(page))

    # --- Data tools ---
    if cormass_api is not None:
        tools.extend(_data_tools(cormass_api))

    # --- Utility tools ---
    tools.extend(_utility_tools(store, task_id, stop_callback=stop_callback, engine=engine))

    return tools


# ===========================================================================
# BROWSER TOOLS
# ===========================================================================

def _browser_tools(page: Page) -> list[ToolDef]:
    """Playwright browser interaction tools."""

    async def browser_navigate(url: str) -> str:
        """Navigate to a URL."""
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = resp.status if resp else "unknown"
            title = await page.title()
            return f"Navigated to {url} (status={status}, title={title!r})"
        except Exception as e:
            return f"Navigation failed: {e}"

    async def browser_click(selector: str) -> str:
        """Click an element by CSS selector."""
        try:
            await page.click(selector, timeout=10000)
            return f"Clicked: {selector}"
        except Exception as e:
            return f"Click failed on {selector}: {e}"

    async def browser_type(selector: str, text: str, clear_first: bool = True) -> str:
        """Type text into an input element."""
        try:
            if clear_first:
                await page.fill(selector, text, timeout=10000)
            else:
                await page.type(selector, text, timeout=10000)
            return f"Typed {len(text)} chars into {selector}"
        except Exception as e:
            return f"Type failed on {selector}: {e}"

    async def browser_screenshot() -> str:
        """Take a screenshot and return a structured accessibility tree of the page.

        Returns a YAML-like accessibility snapshot showing the DOM hierarchy with
        roles, names, values, and interactive states. This is the primary tool for
        understanding what is on the page.
        """
        try:
            title = await page.title()
            url = page.url

            # Use Playwright's accessibility snapshot for structured DOM understanding
            snapshot = await page.accessibility.snapshot()

            def _render_node(node: dict, depth: int = 0, max_depth: int = 8) -> list[str]:
                """Recursively render accessibility tree nodes."""
                if depth > max_depth:
                    return []
                lines: list[str] = []
                indent = "  " * depth
                role = node.get("role", "unknown")
                name = node.get("name", "")
                value = node.get("value", "")

                # Build node description
                desc_parts = [role]
                if name:
                    desc_parts.append(f'"{name}"')
                if value:
                    desc_parts.append(f'value="{value}"')

                # Add useful state flags
                flags = []
                if node.get("focused"):
                    flags.append("focused")
                if node.get("disabled"):
                    flags.append("disabled")
                if node.get("checked") is not None:
                    flags.append(f"checked={node['checked']}")
                if node.get("selected"):
                    flags.append("selected")
                if node.get("expanded") is not None:
                    flags.append(f"expanded={node['expanded']}")
                if node.get("required"):
                    flags.append("required")
                if flags:
                    desc_parts.append(f"[{', '.join(flags)}]")

                line = f"{indent}- {' '.join(desc_parts)}"
                lines.append(line)

                # Recurse into children
                for child in node.get("children", []):
                    lines.extend(_render_node(child, depth + 1, max_depth))

                return lines

            if snapshot:
                tree_lines = _render_node(snapshot)
                tree_text = "\n".join(tree_lines)
                # Truncate if too long (keep first and last parts)
                if len(tree_text) > 8000:
                    tree_text = tree_text[:6000] + "\n  ... [truncated] ...\n" + tree_text[-2000:]
            else:
                tree_text = "(no accessibility tree available)"

            return f"Page: {title}\nURL: {url}\n\nAccessibility Tree:\n{tree_text}"
        except Exception as e:
            return f"Screenshot/analysis failed: {e}"

    async def browser_find_and_click(text: str, role: str = "") -> str:
        """Find and click an element by its visible text or ARIA label.

        Much more reliable than CSS selectors for dynamic React UIs.
        First tries exact match, then substring match.

        Args:
            text: The visible text, label, or placeholder of the element to click.
            role: Optional ARIA role filter (e.g. 'button', 'link', 'textbox', 'menuitem').
        """
        try:
            if role:
                locator = page.get_by_role(role, name=text)
            else:
                # Try role-based approaches first (more reliable)
                for try_role in ["button", "link", "menuitem", "tab", "option"]:
                    loc = page.get_by_role(try_role, name=text)
                    count = await loc.count()
                    if count == 1:
                        await loc.click(timeout=5000)
                        return f"Clicked {try_role} '{text}'"
                    elif count > 1:
                        await loc.first.click(timeout=5000)
                        return f"Clicked first {try_role} '{text}' ({count} matches)"
                # Fallback to get_by_text
                locator = page.get_by_text(text, exact=False)

            count = await locator.count()
            if count == 0:
                return f"No element found with text '{text}'" + (f" and role '{role}'" if role else "")
            await locator.first.click(timeout=5000)
            return f"Clicked element with text '{text}'" + (f" (role={role})" if role else "") + (f" ({count} matches, clicked first)" if count > 1 else "")
        except Exception as e:
            return f"Find-and-click failed for '{text}': {e}"

    async def browser_fill_by_label(label: str, text: str) -> str:
        """Fill a text input identified by its label, placeholder, or ARIA label.

        More reliable than CSS selectors for React UIs.

        Args:
            label: The label, placeholder, or ARIA label of the input field.
            text: The text to type into the field.
        """
        try:
            # Try placeholder first
            locator = page.get_by_placeholder(label)
            count = await locator.count()
            if count > 0:
                await locator.first.fill(text, timeout=5000)
                return f"Filled input (placeholder='{label}') with {len(text)} chars"

            # Try label
            locator = page.get_by_label(label)
            count = await locator.count()
            if count > 0:
                await locator.first.fill(text, timeout=5000)
                return f"Filled input (label='{label}') with {len(text)} chars"

            # Try role textbox with name
            locator = page.get_by_role("textbox", name=label)
            count = await locator.count()
            if count > 0:
                await locator.first.fill(text, timeout=5000)
                return f"Filled textbox (name='{label}') with {len(text)} chars"

            return f"No input found with label/placeholder '{label}'"
        except Exception as e:
            return f"Fill-by-label failed for '{label}': {e}"

    async def browser_get_text(selector: str = "body") -> str:
        """Get text content of an element (default: entire body)."""
        try:
            text = await page.inner_text(selector, timeout=10000)
            if len(text) > 5000:
                text = text[:5000] + "\n... [truncated]"
            return text
        except Exception as e:
            return f"Get text failed on {selector}: {e}"

    async def browser_wait(selector: str, timeout_ms: int = 10000) -> str:
        """Wait for an element to appear."""
        try:
            await page.wait_for_selector(selector, timeout=timeout_ms)
            return f"Element found: {selector}"
        except Exception as e:
            return f"Wait timed out for {selector}: {e}"

    async def browser_scroll(direction: str = "down", amount: int = 500) -> str:
        """Scroll the page."""
        try:
            delta = amount if direction == "down" else -amount
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(0.5)
            return f"Scrolled {direction} by {amount}px"
        except Exception as e:
            return f"Scroll failed: {e}"

    async def browser_get_url() -> str:
        """Get the current page URL."""
        return page.url

    async def browser_press_key(key: str) -> str:
        """Press a keyboard key (e.g. Enter, Tab, Escape)."""
        try:
            await page.keyboard.press(key)
            return f"Pressed key: {key}"
        except Exception as e:
            return f"Key press failed ({key}): {e}"

    async def browser_select(selector: str, value: str) -> str:
        """Select an option from a dropdown."""
        try:
            await page.select_option(selector, value, timeout=10000)
            return f"Selected {value!r} in {selector}"
        except Exception as e:
            return f"Select failed on {selector}: {e}"

    async def browser_get_attribute(selector: str, attribute: str) -> str:
        """Get an attribute value from an element."""
        try:
            val = await page.get_attribute(selector, attribute, timeout=10000)
            return val or "(empty)"
        except Exception as e:
            return f"Get attribute failed ({selector}, {attribute}): {e}"

    async def browser_evaluate(expression: str) -> str:
        """Evaluate a JavaScript expression in the page context."""
        try:
            result = await page.evaluate(expression)
            if isinstance(result, (dict, list)):
                return json.dumps(result, default=str)[:5000]
            return str(result)[:5000]
        except Exception as e:
            return f"JS evaluation failed: {e}"

    return [
        ToolDef(
            name="browser_navigate",
            description="Navigate the browser to a URL. Returns page title and HTTP status.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to navigate to"},
                },
                "required": ["url"],
            },
            handler=browser_navigate,
        ),
        ToolDef(
            name="browser_click",
            description="Click an element on the page by CSS selector.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the element to click"},
                },
                "required": ["selector"],
            },
            handler=browser_click,
        ),
        ToolDef(
            name="browser_type",
            description="Type text into an input or textarea. By default clears the field first.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input element"},
                    "text": {"type": "string", "description": "Text to type"},
                    "clear_first": {"type": "boolean", "description": "Clear the field before typing (default: true)", "default": True},
                },
                "required": ["selector", "text"],
            },
            handler=browser_type,
        ),
        ToolDef(
            name="browser_screenshot",
            description=(
                "Analyze the current page by returning its accessibility tree. "
                "Shows the full DOM hierarchy with roles, names, values, and states. "
                "Use this to understand what elements are on the page and how to interact with them. "
                "Interactive elements show roles like 'button', 'link', 'textbox', 'menuitem'. "
                "Use the element names with browser_find_and_click or browser_fill_by_label."
            ),
            parameters={"type": "object", "properties": {}},
            handler=browser_screenshot,
        ),
        ToolDef(
            name="browser_get_text",
            description="Get the text content of a page element. Default returns entire page body text.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector (default: 'body')", "default": "body"},
                },
            },
            handler=browser_get_text,
        ),
        ToolDef(
            name="browser_wait",
            description="Wait for an element to appear on the page.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector to wait for"},
                    "timeout_ms": {"type": "integer", "description": "Max wait in milliseconds (default: 10000)", "default": 10000},
                },
                "required": ["selector"],
            },
            handler=browser_wait,
        ),
        ToolDef(
            name="browser_scroll",
            description="Scroll the page up or down.",
            parameters={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down"], "description": "Scroll direction", "default": "down"},
                    "amount": {"type": "integer", "description": "Pixels to scroll (default: 500)", "default": 500},
                },
            },
            handler=browser_scroll,
        ),
        ToolDef(
            name="browser_get_url",
            description="Get the current page URL.",
            parameters={"type": "object", "properties": {}},
            handler=browser_get_url,
        ),
        ToolDef(
            name="browser_press_key",
            description="Press a keyboard key (e.g. Enter, Tab, Escape, ArrowDown).",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key name to press"},
                },
                "required": ["key"],
            },
            handler=browser_press_key,
        ),
        ToolDef(
            name="browser_select",
            description="Select an option from a dropdown/select element.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the select element"},
                    "value": {"type": "string", "description": "Option value to select"},
                },
                "required": ["selector", "value"],
            },
            handler=browser_select,
        ),
        ToolDef(
            name="browser_get_attribute",
            description="Get an HTML attribute value from an element.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the element"},
                    "attribute": {"type": "string", "description": "Attribute name (e.g. href, src, value)"},
                },
                "required": ["selector", "attribute"],
            },
            handler=browser_get_attribute,
        ),
        ToolDef(
            name="browser_evaluate",
            description="Run a JavaScript expression in the page and return the result. Use for complex DOM queries.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "JavaScript expression to evaluate"},
                },
                "required": ["expression"],
            },
            handler=browser_evaluate,
        ),
        ToolDef(
            name="browser_find_and_click",
            description=(
                "Click an element by its visible text or ARIA label. Much more reliable than CSS selectors "
                "for dynamic React UIs like Instagram, Facebook, etc. Use names from the accessibility tree "
                "(browser_screenshot output). Optionally filter by ARIA role (button, link, textbox, menuitem, tab, option)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The visible text, label, or ARIA name of the element to click"},
                    "role": {"type": "string", "description": "Optional ARIA role filter (e.g. 'button', 'link', 'textbox')", "default": ""},
                },
                "required": ["text"],
            },
            handler=browser_find_and_click,
        ),
        ToolDef(
            name="browser_fill_by_label",
            description=(
                "Fill a text input by its label, placeholder, or ARIA label. More reliable than CSS selectors. "
                "Use placeholder text or label names from the accessibility tree (browser_screenshot output)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "The label, placeholder, or ARIA label of the input"},
                    "text": {"type": "string", "description": "The text to type into the input"},
                },
                "required": ["label", "text"],
            },
            handler=browser_fill_by_label,
        ),
    ]


# ===========================================================================
# DATA TOOLS
# ===========================================================================

def _data_tools(cormass_api: Any) -> list[ToolDef]:
    """Cormass Leads API query tools."""

    async def leads_list_canvases() -> str:
        """List available lead canvases from Cormass Leads."""
        try:
            canvases = cormass_api.list_canvases()
            if not canvases:
                return "No canvases found or API connection failed."
            lines = ["Available canvases:"]
            for c in canvases:
                lines.append(f"  ID={c.get('id')} | {c.get('name', 'Unnamed')} | {c.get('itemCount', 0)} leads")
            return "\n".join(lines)
        except Exception as e:
            return f"Failed to list canvases: {e}"

    async def leads_get_canvas(canvas_id: int) -> str:
        """Get all leads from a canvas. Returns lead names, handles, and business info."""
        try:
            leads = cormass_api.pull_canvas(canvas_id)
            if not leads:
                return f"Canvas {canvas_id} has no leads."
            lines = [f"Canvas {canvas_id}: {len(leads)} leads"]
            for i, lead in enumerate(leads[:30]):  # Limit to 30 for context window
                name = lead.get("name", "Unknown")
                handle = lead.get("instagram_handle", "")
                phone = lead.get("phone_number", "")
                email = lead.get("email", "")
                btype = lead.get("business_type", "")
                loc = lead.get("location", "")
                parts = [f"  {i+1}. {name}"]
                if btype:
                    parts.append(f"type={btype}")
                if loc:
                    parts.append(f"loc={loc[:40]}")
                if handle:
                    parts.append(f"ig=@{handle}")
                if phone:
                    parts.append(f"phone={phone}")
                if email:
                    parts.append(f"email={email}")
                lines.append(" | ".join(parts))
            if len(leads) > 30:
                lines.append(f"  ... and {len(leads) - 30} more leads")
            return "\n".join(lines)
        except Exception as e:
            return f"Failed to get canvas {canvas_id}: {e}"

    async def leads_update_status(
        business_id: str,
        channel: str,
        state: str,
        message_preview: str = "",
    ) -> str:
        """Update the outreach status for a lead in Cormass Leads."""
        try:
            success = cormass_api.sync_status(
                business_id=business_id,
                channel=channel,
                state=state,
                message_preview=message_preview,
            )
            if success:
                return f"Status updated: {business_id} -> {channel}/{state}"
            return f"Status update failed for {business_id}"
        except Exception as e:
            return f"Status update error: {e}"

    return [
        ToolDef(
            name="leads_list_canvases",
            description="List all available lead canvases from the Cormass Leads database. Each canvas contains a collection of business leads.",
            parameters={"type": "object", "properties": {}},
            handler=leads_list_canvases,
        ),
        ToolDef(
            name="leads_get_canvas",
            description="Get all leads from a specific canvas by ID. Returns business names, contact info, social handles, and metadata.",
            parameters={
                "type": "object",
                "properties": {
                    "canvas_id": {"type": "integer", "description": "The canvas ID to fetch leads from"},
                },
                "required": ["canvas_id"],
            },
            handler=leads_get_canvas,
        ),
        ToolDef(
            name="leads_update_status",
            description="Update the outreach status for a lead in the Cormass Leads system. Call this after successfully contacting a lead.",
            parameters={
                "type": "object",
                "properties": {
                    "business_id": {"type": "string", "description": "The Cormass business ID of the lead"},
                    "channel": {"type": "string", "description": "Contact channel used (e.g. 'instagram_dm', 'email', 'whatsapp')"},
                    "state": {"type": "string", "description": "Status state (e.g. 'sent', 'replied', 'converted', 'rejected')"},
                    "message_preview": {"type": "string", "description": "First 500 chars of the message sent", "default": ""},
                },
                "required": ["business_id", "channel", "state"],
            },
            handler=leads_update_status,
        ),
    ]


# ===========================================================================
# UTILITY TOOLS
# ===========================================================================

def _utility_tools(store: Any | None, task_id: int | None, stop_callback: Any | None = None, engine: Any | None = None) -> list[ToolDef]:
    """Logging, delay, and progress reporting tools."""

    async def report_progress(message: str, percentage: int = -1) -> str:
        """Report progress to the user. The message will be shown in the UI activity log."""
        level = "info"
        if store and task_id:
            try:
                store.log_activity(
                    message=f"[Agent] {message}",
                    level=level,
                    campaign_id=task_id,
                )
            except Exception:
                pass
        logger.info("[Agent progress] %s", message)
        return f"Progress reported: {message}"

    async def log_message_sent(
        lead_name: str,
        channel: str,
        message_preview: str,
        success: bool = True,
    ) -> str:
        """Log that a message was sent to a lead. Records in the activity log and outreach log."""
        # Rate limiting check (Item 11)
        if engine and success:
            allowed, reason = engine.check_rate_limits()
            if not allowed:
                level = "warning"
                log_msg = f"Rate limit: {reason}. Message to {lead_name} blocked."
                if store:
                    try:
                        store.log_activity(
                            message=log_msg,
                            level=level,
                            campaign_id=task_id,
                            details=message_preview[:500],
                        )
                    except Exception:
                        pass
                logger.warning(log_msg)
                return log_msg

        level = "success" if success else "error"
        status = "sent" if success else "failed"
        log_msg = f"Message {status}: {lead_name} via {channel}"

        # Increment message counters (Item 7)
        if engine:
            engine.increment_message_count(success=success)

        if store:
            try:
                store.log_activity(
                    message=log_msg,
                    level=level,
                    campaign_id=task_id,
                    details=message_preview[:500],
                )
            except Exception:
                pass

        logger.info(log_msg)
        return log_msg

    async def delay(seconds: int = 5, reason: str = "") -> str:
        """Wait for a specified number of seconds. Use between actions to appear human-like."""
        seconds = max(1, min(seconds, 300))  # Clamp to 1-300
        if reason:
            logger.info("Delay %ds: %s", seconds, reason)
        await asyncio.sleep(seconds)
        return f"Waited {seconds} seconds"

    async def finish_task(summary: str) -> str:
        """Mark the current task as complete with a summary of what was accomplished."""
        if store and task_id:
            try:
                store.log_activity(
                    message=f"[Agent] Task complete: {summary}",
                    level="success",
                    campaign_id=task_id,
                )
            except Exception:
                pass
        # Signal the engine to stop the agent loop
        if stop_callback:
            try:
                stop_callback()
            except Exception:
                pass
        return f"Task finished: {summary}"

    return [
        ToolDef(
            name="report_progress",
            description="Report progress to the user. The message appears in the activity log UI.",
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Progress update message"},
                    "percentage": {"type": "integer", "description": "Completion percentage (0-100, or -1 if unknown)", "default": -1},
                },
                "required": ["message"],
            },
            handler=report_progress,
        ),
        ToolDef(
            name="log_message_sent",
            description="Log that a message was sent to a lead. Records the outreach attempt.",
            parameters={
                "type": "object",
                "properties": {
                    "lead_name": {"type": "string", "description": "Name of the lead/business"},
                    "channel": {"type": "string", "description": "Channel used (e.g. 'instagram_dm', 'email')"},
                    "message_preview": {"type": "string", "description": "The message that was sent (first 500 chars)"},
                    "success": {"type": "boolean", "description": "Whether the send was successful", "default": True},
                },
                "required": ["lead_name", "channel", "message_preview"],
            },
            handler=log_message_sent,
        ),
        ToolDef(
            name="delay",
            description="Wait for a number of seconds. Use between actions to simulate human behavior and respect rate limits.",
            parameters={
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "Seconds to wait (1-300)", "default": 5},
                    "reason": {"type": "string", "description": "Why the delay is needed", "default": ""},
                },
            },
            handler=delay,
        ),
        ToolDef(
            name="finish_task",
            description="Mark the current task as complete and provide a summary of accomplishments.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Summary of what was accomplished"},
                },
                "required": ["summary"],
            },
            handler=finish_task,
        ),
    ]
