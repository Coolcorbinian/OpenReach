"""Prompt templates for LLM-powered message generation."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are a professional outreach assistant. Your job is to write short, personalized Instagram DMs to business owners or managers.

Rules:
- Keep messages under 300 characters (Instagram DM best practice)
- Be professional but approachable
- Reference something specific about the recipient's business
- Include a clear, low-pressure call to action
- Never be pushy, spammy, or use ALL CAPS
- Do not use emojis excessively (1-2 max)
- Write in the same language as the business name/description if non-English
- Output ONLY the message text, nothing else (no quotes, no labels, no explanation)"""


def build_outreach_prompt(lead: dict[str, Any]) -> str:
    """Build a prompt for generating a personalized outreach message.

    Args:
        lead: Dictionary with lead data (name, business_type, reviews, notes, etc.)

    Returns:
        The formatted prompt string
    """
    parts = ["Write a personalized Instagram DM to this business:\n"]

    if lead.get("name"):
        parts.append(f"Business: {lead['name']}")

    if lead.get("business_type") or lead.get("category"):
        parts.append(f"Type: {lead.get('business_type') or lead.get('category')}")

    if lead.get("location") or lead.get("address"):
        parts.append(f"Location: {lead.get('location') or lead.get('address')}")

    if lead.get("rating"):
        parts.append(f"Rating: {lead['rating']}/5")

    if lead.get("review_count"):
        parts.append(f"Reviews: {lead['review_count']}")

    if lead.get("notes"):
        parts.append(f"Notes: {lead['notes']}")

    if lead.get("pain_points"):
        parts.append(f"Known pain points: {lead['pain_points']}")

    if lead.get("website"):
        parts.append(f"Website: {lead['website']}")

    # Context about what we're offering
    if lead.get("offer_context"):
        parts.append(f"\nOur offer: {lead['offer_context']}")

    return "\n".join(parts)


def build_reply_analysis_prompt(conversation: list[dict[str, str]]) -> str:
    """Build a prompt to analyze a reply and suggest next action.

    Args:
        conversation: List of message dicts with 'role' and 'content'

    Returns:
        The formatted prompt string
    """
    parts = ["Analyze this Instagram DM conversation and suggest the best next action:\n"]

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
