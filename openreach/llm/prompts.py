"""Prompt templates for the OpenReach agent.

Architecture:
- build_agent_system_prompt(): Primary prompt for the tool-calling agent
- Legacy prompt builders kept for backward compatibility
"""

from __future__ import annotations

import re
from typing import Any


# ---------- Agent System Prompt ----------

AGENT_SYSTEM_PROMPT = """\
You are OpenReach Agent, an AI assistant that operates a web browser to complete \
outreach and research tasks for the user. You interact with websites by calling \
browser tools (navigate, click, type, screenshot, etc.) and data tools \
(leads_list_canvases, leads_get_canvas, etc.).

## Core Rules

1. **You control the browser.** The user cannot see the browser -- they rely on \
your reports. Always use browser_screenshot after navigation or significant page \
changes to understand the current state. browser_screenshot returns an \
accessibility tree showing the DOM hierarchy with roles, names, and states.

2. **Use ARIA-based tools for interactions.** Prefer browser_find_and_click \
(clicks by visible text or ARIA label) and browser_fill_by_label (fills inputs \
by label/placeholder) over browser_click (CSS selector) and browser_type (CSS \
selector). The ARIA tools are much more reliable on dynamic React UIs like \
Instagram, Facebook, and modern single-page apps. Use the element names you \
see in browser_screenshot output.

3. **Be methodical.** Before clicking or typing, confirm you have the right \
element using browser_screenshot. If an element is not found, try scrolling or \
waiting.

4. **Report progress.** Use report_progress to keep the user informed of what \
you are doing. Be specific ("Navigating to Instagram login page", "Typing \
message to @businessname").

5. **Human-like behavior.** When interacting with social media or websites:
   - Add delays between actions (use the delay tool with 2-10 seconds)
   - Do not perform actions faster than a human would
   - Respect rate limits and site rules

6. **Handle errors gracefully.** If a page does not load, an element is not \
found, or a login fails, report the error via report_progress and attempt \
recovery (reload page, try alternative selectors, etc.).

7. **Complete the task.** Keep working until the task is fully done, then call \
finish_task with a summary. If you cannot complete a task, explain why.

8. **No fabrication.** Only report what you actually see on the page. Do not \
invent data or pretend actions succeeded if they did not.

9. **Privacy.** Never reveal passwords or API keys in your reasoning or tool \
call arguments. If credentials are needed, the user provides them separately.

## Available Data

If the user has connected their Cormass Leads account, you can use data tools \
to access their business lead database. Use leads_list_canvases to see available \
lead collections, and leads_get_canvas to load lead details.

## Message Writing Guidelines

When writing outreach messages:
- Keep messages concise and professional
- Personalize based on the lead's business data
- Do not be pushy, spammy, or use ALL CAPS
- Write in the lead's likely language (based on location/business name)
- After sending, log the message using log_message_sent
"""


def build_agent_system_prompt(
    campaign: dict[str, Any],
    leads: list[dict[str, Any]] | None = None,
) -> str:
    """Build the full system prompt for the agent.

    Args:
        campaign: Task/campaign dict with user_prompt, additional_notes, etc.
        leads: Optional lead list for context

    Returns:
        Complete system prompt string
    """
    parts: list[str] = [AGENT_SYSTEM_PROMPT]

    # Task-specific context from user prompt
    user_prompt = campaign.get("user_prompt", "").strip()
    if user_prompt:
        parts.append(f"\n## User's Task Instructions\n{user_prompt}")

    additional_notes = campaign.get("additional_notes", "").strip()
    if additional_notes:
        parts.append(f"\n## Additional Context\n{additional_notes}")

    # Lead count info
    if leads:
        parts.append(f"\n## Lead Data\nYou have {len(leads)} leads loaded. "
                     f"Lead details will be provided in the user message.")

    return "\n".join(parts)


# ---------- Legacy Platform Configs (kept for backward compatibility) ----------

PLATFORM_CONFIGS: dict[str, dict[str, Any]] = {
    "instagram": {
        "name": "Instagram",
        "dm_label": "Instagram DM",
        "max_chars": 1000,
        "best_practice_chars": 300,
        "guidelines": (
            "- Keep messages under 300 characters (Instagram DM best practice)\n"
            "- Be professional but approachable\n"
            "- Do not use excessive emojis (1-2 max)\n"
            "- Never be pushy, spammy, or use ALL CAPS\n"
            "- Output ONLY the message text -- no quotes, no labels, no explanation\n"
            "- Do not include greetings like 'Hi' if the username is unknown"
        ),
    },
    "linkedin": {
        "name": "LinkedIn",
        "dm_label": "LinkedIn message",
        "max_chars": 1900,
        "best_practice_chars": 500,
        "guidelines": (
            "- Keep messages under 500 characters for connection requests\n"
            "- Be professional and reference shared industry context\n"
            "- Include a clear value proposition\n"
            "- Output ONLY the message text -- no quotes, no labels, no explanation"
        ),
    },
    "twitter": {
        "name": "Twitter / X",
        "dm_label": "Twitter DM",
        "max_chars": 10000,
        "best_practice_chars": 280,
        "guidelines": (
            "- Keep messages concise, under 280 characters preferred\n"
            "- Be direct and casual-professional\n"
            "- Output ONLY the message text -- no quotes, no labels, no explanation"
        ),
    },
    "email": {
        "name": "Email",
        "dm_label": "cold email",
        "max_chars": 5000,
        "best_practice_chars": 1500,
        "guidelines": (
            "- Write a subject line on the first line, prefixed with 'Subject: '\n"
            "- Keep the body under 200 words\n"
            "- Be professional, include a clear CTA\n"
            "- Personalize based on the recipient's business\n"
            "- Output ONLY the email (subject + body), no extra commentary"
        ),
    },
}


def get_platform_config(platform: str) -> dict[str, Any]:
    """Get the configuration for a given platform, with fallback to Instagram."""
    return PLATFORM_CONFIGS.get(platform, PLATFORM_CONFIGS["instagram"])


# ---------- Legacy System prompt builder ----------

def build_system_prompt(campaign: dict[str, Any]) -> str:
    """Build the LLM system prompt from a campaign configuration (legacy)."""
    platform = campaign.get("platform", "instagram")
    pcfg = get_platform_config(platform)
    user_prompt = campaign.get("user_prompt", "").strip()
    additional_notes = campaign.get("additional_notes", "").strip()

    parts: list[str] = []

    if user_prompt:
        parts.append(user_prompt)
    else:
        parts.append(
            f"You are a professional outreach assistant. Your job is to write short, "
            f"personalized {pcfg['dm_label']}s to business owners or managers."
        )

    parts.append(f"\n--- {pcfg['name']} Guidelines ---")
    parts.append(pcfg["guidelines"])

    parts.append(
        "\n--- Language ---\n"
        "Write in the same language as the business name/location if it appears non-English. "
        "Default to English otherwise."
    )

    if additional_notes:
        parts.append(f"\n--- Additional Context ---\n{additional_notes}")

    return "\n".join(parts)


# ---------- Static message builder ----------

def build_static_message(template: str, lead: dict[str, Any]) -> str:
    """Substitute {{placeholders}} in a static message template."""
    def _replace(match: re.Match) -> str:
        key = match.group(1).strip().lower()
        value = lead.get(key, "")
        if value is None:
            return ""
        return str(value)

    result = re.sub(r"\{\{(\w+)\}\}", _replace, template)
    result = re.sub(r"  +", " ", result).strip()
    return result


# ---------- Dynamic prompt builder ----------

def build_dynamic_prompt(
    lead: dict[str, Any],
    scraped_profile: dict[str, Any] | None = None,
) -> str:
    """Build the user-message prompt for dynamic (LLM-generated) outreach (legacy)."""
    parts: list[str] = [
        "Write a personalized outreach message to this business. "
        "Use the data below to make it specific and relevant.\n"
    ]

    parts.append("=== BUSINESS DATA ===")
    if lead.get("name"):
        parts.append(f"Business Name: {lead['name']}")
    if lead.get("business_type"):
        parts.append(f"Industry/Type: {lead['business_type']}")
    if lead.get("location"):
        parts.append(f"Location: {lead['location']}")
    if lead.get("rating"):
        parts.append(f"Rating: {lead['rating']}/5")
    if lead.get("review_count"):
        parts.append(f"Review Count: {lead['review_count']}")
    if lead.get("website"):
        parts.append(f"Website: {lead['website']}")
    if lead.get("notes"):
        parts.append(f"Notes: {lead['notes']}")
    if lead.get("pain_points"):
        parts.append(f"Known Pain Points: {lead['pain_points']}")
    if lead.get("offer_context"):
        parts.append(f"Our Offer: {lead['offer_context']}")

    if scraped_profile:
        parts.append("\n=== SOCIAL MEDIA PROFILE ===")
        if scraped_profile.get("display_name"):
            parts.append(f"Display Name: {scraped_profile['display_name']}")
        if scraped_profile.get("bio"):
            parts.append(f"Bio: {scraped_profile['bio']}")
        if scraped_profile.get("followers"):
            parts.append(f"Followers: {scraped_profile['followers']}")
        if scraped_profile.get("following"):
            parts.append(f"Following: {scraped_profile['following']}")
        if scraped_profile.get("post_count"):
            parts.append(f"Posts: {scraped_profile['post_count']}")
        if scraped_profile.get("recent_posts"):
            posts_text = "; ".join(
                str(p)[:120] for p in scraped_profile["recent_posts"][:5]
            )
            parts.append(f"Recent Posts: {posts_text}")
        if scraped_profile.get("category"):
            parts.append(f"Profile Category: {scraped_profile['category']}")
        if scraped_profile.get("external_url"):
            parts.append(f"Profile Link: {scraped_profile['external_url']}")
        if scraped_profile.get("is_verified"):
            parts.append("Verified Account: Yes")

    return "\n".join(parts)


# ---------- Reply analysis prompt ----------

def build_reply_analysis_prompt(conversation: list[dict[str, str]]) -> str:
    """Build a prompt to analyze a reply and suggest next action (legacy)."""
    parts = ["Analyze this conversation and suggest the best next action:\n"]

    for msg in conversation:
        role = "Us" if msg["role"] == "sent" else "Them"
        parts.append(f"{role}: {msg['content']}")

    parts.append(
        "\nRespond with a JSON object: "
        '{"sentiment": "positive|neutral|negative", '
        '"interested": true|false, '
        '"suggested_reply": "...", '
        '"action": "reply|wait|mark_converted|mark_rejected"}'
    )

    return "\n".join(parts)


# ---------- Suggested Task Templates ----------

TASK_TEMPLATES = {
    "instagram_dm": {
        "name": "Instagram DM Outreach",
        "prompt": (
            "For each lead in my list, go to Instagram, find their profile, "
            "and send them a personalized DM introducing our services. "
            "Personalize each message based on their business type and location. "
            "Wait 30-60 seconds between each message. "
            "Log each message sent using log_message_sent."
        ),
    },
    "email_outreach": {
        "name": "Email Outreach",
        "prompt": (
            "For each lead that has an email address, compose and send a "
            "personalized cold email. Navigate to my email provider, compose "
            "a new message, enter the lead's email, write a subject and body "
            "personalized to their business, and send it. Log each email sent."
        ),
    },
    "research": {
        "name": "Lead Research",
        "prompt": (
            "For each lead in my list, research their business online. "
            "Visit their website, check their social media profiles, and "
            "compile key information: services offered, team size, recent news, "
            "and potential pain points. Report your findings using report_progress."
        ),
    },
    "social_engagement": {
        "name": "Social Media Engagement",
        "prompt": (
            "For each lead, visit their social media profiles and engage "
            "authentically: like 2-3 recent posts, leave a thoughtful comment "
            "on one post, and follow their account. Wait 20-40 seconds between "
            "each action. This is a warm-up before direct outreach."
        ),
    },
}
