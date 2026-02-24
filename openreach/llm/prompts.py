"""Prompt templates for LLM-powered message generation.

Architecture:
- The user's campaign prompt becomes the SYSTEM message (defines the LLM's role).
- The lead data + scraped profile become the USER message (context for the LLM).
- Static mode: pure template substitution, no LLM call needed.
- Dynamic mode: LLM generates a message using scraped social profile context.
"""

from __future__ import annotations

import re
from typing import Any


# ---------- Platform-specific configuration ----------

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


# ---------- System prompt builder ----------

def build_system_prompt(campaign: dict[str, Any]) -> str:
    """Build the LLM system prompt from a campaign configuration.

    The user's campaign prompt (user_prompt) defines the LLM's ROLE.
    Platform guidelines and additional notes are appended.

    Args:
        campaign: Campaign dict with keys: user_prompt, additional_notes, platform

    Returns:
        The system prompt string
    """
    platform = campaign.get("platform", "instagram")
    pcfg = get_platform_config(platform)
    user_prompt = campaign.get("user_prompt", "").strip()
    additional_notes = campaign.get("additional_notes", "").strip()

    parts: list[str] = []

    # Role definition from user
    if user_prompt:
        parts.append(user_prompt)
    else:
        parts.append(
            f"You are a professional outreach assistant. Your job is to write short, "
            f"personalized {pcfg['dm_label']}s to business owners or managers."
        )

    # Platform rules
    parts.append(f"\n--- {pcfg['name']} Guidelines ---")
    parts.append(pcfg["guidelines"])

    # Language instruction
    parts.append(
        "\n--- Language ---\n"
        "Write in the same language as the business name/location if it appears non-English. "
        "Default to English otherwise."
    )

    # Additional notes from user
    if additional_notes:
        parts.append(f"\n--- Additional Context ---\n{additional_notes}")

    return "\n".join(parts)


# ---------- Static message builder ----------

def build_static_message(template: str, lead: dict[str, Any]) -> str:
    """Substitute {{placeholders}} in a static message template.

    Supported placeholders:
        {{name}}, {{business_type}}, {{location}}, {{rating}},
        {{review_count}}, {{website}}, {{instagram_handle}},
        {{notes}}, {{pain_points}}, {{offer_context}}

    Unknown placeholders are replaced with empty string.

    Args:
        template: The message template string
        lead: Lead data dictionary

    Returns:
        The filled-in message string
    """
    def _replace(match: re.Match) -> str:  # type: ignore[type-arg]
        key = match.group(1).strip().lower()
        value = lead.get(key, "")
        if value is None:
            return ""
        return str(value)

    result = re.sub(r"\{\{(\w+)\}\}", _replace, template)
    # Clean up double spaces / leading/trailing whitespace
    result = re.sub(r"  +", " ", result).strip()
    return result


# ---------- Dynamic prompt builder ----------

def build_dynamic_prompt(
    lead: dict[str, Any],
    scraped_profile: dict[str, Any] | None = None,
) -> str:
    """Build the user-message prompt for dynamic (LLM-generated) outreach.

    Combines lead data with scraped social profile information so the LLM
    can write a highly personalized message.

    Args:
        lead: Lead data dictionary
        scraped_profile: Optional scraped social media profile data

    Returns:
        The formatted user prompt string
    """
    parts: list[str] = [
        "Write a personalized outreach message to this business. "
        "Use the data below to make it specific and relevant.\n"
    ]

    # --- Lead data ---
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

    # --- Scraped social profile ---
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


# ---------- Reply analysis prompt (for future conversation flow) ----------

def build_reply_analysis_prompt(conversation: list[dict[str, str]]) -> str:
    """Build a prompt to analyze a reply and suggest next action.

    Args:
        conversation: List of message dicts with 'role' and 'content'

    Returns:
        The formatted prompt string
    """
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
