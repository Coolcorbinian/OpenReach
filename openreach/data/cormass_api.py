"""Cormass Leads API client for pulling lead data and syncing contact status."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://cormass.com/wp-json/leads/v1"


class CormassApiClient:
    """Client for the Cormass Leads REST API using API key authentication."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def list_canvases(self) -> list[dict[str, Any]]:
        """List all canvases accessible to this API key.

        Returns:
            List of canvas dicts with id, name, itemCount, createdAt, updatedAt.
            Returns empty list on error.
        """
        url = f"{self.base_url}/canvases"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, headers=self._headers())
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    logger.warning("Unexpected canvases response: %s", type(data))
                    return []
                return data
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to list canvases: %s", e)
            return []
        except httpx.ConnectError:
            logger.warning("Cannot reach Cormass API at %s", self.base_url)
            return []

    def pull_canvas(self, canvas_id: int) -> list[dict[str, Any]]:
        """Pull all leads from a Cormass Leads canvas.

        Canvas items have structure:
            { data: {name, phone_number, full_address, ...}, source: {raw: {business_id, ...}} }

        The actual lead fields live in source.raw (full) with data containing
        user-edited overrides. We merge them: raw as base, data as override.

        Args:
            canvas_id: The canvas ID to pull from

        Returns:
            List of lead dicts ready for DataStore.add_leads()
        """
        url = f"{self.base_url}/canvases/{canvas_id}"

        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, headers=self._headers())
            response.raise_for_status()
            resp = response.json()

        # The response has { canvas: { items: [...] } }
        canvas = resp.get("canvas") or {}
        items = canvas.get("items") or []

        if not items:
            logger.warning("Canvas %d has no items", canvas_id)
            return []

        leads = []
        for item in items:
            if not isinstance(item, dict):
                continue

            # Merge source.raw as base, then data as overrides
            raw = {}
            source = item.get("source") or {}
            if isinstance(source, dict):
                raw = source.get("raw") or {}

            data = item.get("data") or {}
            enrichment = item.get("enrichment") or {}

            # Raw is the base, data overrides any key present
            merged = {**raw, **data}

            # Build business_type from types array (e.g. ["Coffeeshop", "Cafe"])
            types_val = merged.get("types") or []
            if isinstance(types_val, list):
                business_type = ", ".join(str(t) for t in types_val[:3])
            else:
                business_type = str(types_val)

            lead = {
                "name": str(merged.get("name") or "").strip(),
                "instagram_handle": _extract_instagram(merged, enrichment),
                "phone_number": str(merged.get("phone_number") or merged.get("phone") or "").strip(),
                "email": str(merged.get("email") or "").strip(),
                "social_handles": json.dumps(_extract_all_socials(merged, enrichment)),
                "business_type": business_type.strip(),
                "location": str(merged.get("full_address") or merged.get("address") or "").strip(),
                "rating": _safe_float(merged.get("rating")),
                "review_count": _safe_int(merged.get("review_count")),
                "website": str(merged.get("website") or "").strip(),
                "enrichment_json": json.dumps(enrichment) if enrichment else None,
                "notes": "",
                "cormass_business_id": str(merged.get("business_id") or merged.get("place_id") or "").strip(),
                "cormass_canvas_id": canvas_id,
                "source": "cormass_api",
            }
            # Only add leads that have at least a name or business_id
            if lead["name"] or lead["cormass_business_id"]:
                leads.append(lead)

        logger.info("Pulled %d leads from canvas %d", len(leads), canvas_id)
        return leads

    def sync_status(
        self,
        business_id: str,
        channel: str,
        state: str,
        canvas_id: int = 0,
        message_preview: str | None = None,
    ) -> bool:
        """Sync a contact status back to Cormass Leads.

        Args:
            business_id: The Cormass business ID
            channel: Channel used (e.g., 'instagram_dm')
            state: Status state (e.g., 'sent', 'replied')
            canvas_id: Optional canvas ID
            message_preview: Optional first 500 chars of message

        Returns:
            True if sync was successful
        """
        url = f"{self.base_url}/leads/{business_id}/status"

        payload: dict[str, Any] = {
            "channel": channel,
            "state": state,
            "source": "openreach",
        }
        if canvas_id:
            payload["canvas_id"] = canvas_id
        if message_preview:
            payload["message_preview"] = message_preview[:500]

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
                logger.debug("Synced status for %s: %s/%s", business_id, channel, state)
                return True
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to sync status for %s: %s", business_id, e)
            return False
        except httpx.ConnectError:
            logger.warning("Cannot reach Cormass API at %s", self.base_url)
            return False

    def get_statuses(self, canvas_id: int) -> list[dict[str, Any]]:
        """Get all contact statuses for a canvas.

        Args:
            canvas_id: The canvas ID

        Returns:
            List of status dicts
        """
        url = f"{self.base_url}/canvases/{canvas_id}/statuses"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, headers=self._headers())
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPStatusError, httpx.ConnectError) as e:
            logger.warning("Failed to get statuses for canvas %d: %s", canvas_id, e)
            return []

    def check_connection(self) -> bool:
        """Verify the API key works by listing canvases (needs read_canvases permission)."""
        try:
            canvases = self.list_canvases()
            # If we get a list (even empty), the auth worked
            return isinstance(canvases, list)
        except Exception:
            return False


def _safe_float(val: Any) -> float | None:
    """Safely convert a value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    """Safely convert a value to int."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _extract_instagram(item: dict[str, Any], enrichment: dict[str, Any] | None = None) -> str:
    """Try to extract Instagram handle from a lead item and enrichment data."""
    # Direct field
    handle = item.get("instagram") or item.get("instagram_handle") or ""
    if handle:
        return handle.lstrip("@")

    # From enrichment socials (e.g. enrichment.socials.instagram)
    if enrichment and isinstance(enrichment, dict):
        socials = enrichment.get("socials") or {}
        if isinstance(socials, dict):
            ig = socials.get("instagram", "")
            if ig:
                ig = ig.rstrip("/").split("/")[-1]
                return ig.lstrip("@")

    # From social links in merged data
    socials = item.get("socialLinks") or item.get("social_links") or {}
    if isinstance(socials, dict):
        ig = socials.get("instagram", "")
        if ig:
            # Extract handle from URL
            ig = ig.rstrip("/").split("/")[-1]
            return ig.lstrip("@")

    return ""


def _extract_all_socials(item: dict[str, Any], enrichment: dict[str, Any] | None = None) -> dict[str, str]:
    """Extract all social media handles from a lead item and enrichment data."""
    socials: dict[str, str] = {}

    # Instagram
    ig = _extract_instagram(item, enrichment)
    if ig:
        socials["instagram"] = ig

    # From enrichment socials
    if enrichment and isinstance(enrichment, dict):
        enrichment_socials = enrichment.get("socials") or {}
        if isinstance(enrichment_socials, dict):
            for platform in ("facebook", "twitter", "linkedin", "youtube", "tiktok", "pinterest"):
                val = enrichment_socials.get(platform, "")
                if val:
                    # Extract handle from URL if needed
                    val = val.rstrip("/").split("/")[-1]
                    if val:
                        socials[platform] = val

    # From social links in merged data
    social_links = item.get("socialLinks") or item.get("social_links") or {}
    if isinstance(social_links, dict):
        for platform, url in social_links.items():
            if url and platform not in socials:
                handle = url.rstrip("/").split("/")[-1]
                if handle:
                    socials[platform] = handle

    return socials
