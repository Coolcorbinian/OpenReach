"""Cormass Leads API client for pulling lead data and syncing contact status."""

from __future__ import annotations

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

    def pull_canvas(self, canvas_id: int) -> list[dict[str, Any]]:
        """Pull all leads from a Cormass Leads canvas.

        Args:
            canvas_id: The canvas ID to pull from

        Returns:
            List of lead dicts with business data
        """
        url = f"{self.base_url}/canvases/{canvas_id}"

        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()

        # Parse canvas JSON to extract items
        canvas_json = data.get("canvasJson")
        if not canvas_json:
            logger.warning("Canvas %d has no items", canvas_id)
            return []

        items = canvas_json if isinstance(canvas_json, list) else canvas_json.get("items", [])

        leads = []
        for item in items:
            lead = {
                "name": item.get("title") or item.get("name", ""),
                "instagram_handle": _extract_instagram(item),
                "business_type": item.get("type") or item.get("category", ""),
                "location": item.get("address", ""),
                "rating": item.get("rating"),
                "review_count": item.get("reviews"),
                "website": item.get("website", ""),
                "notes": "",
                "cormass_business_id": item.get("businessId") or item.get("business_id", ""),
                "cormass_canvas_id": canvas_id,
                "source": "cormass_api",
            }
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
        """Verify the API key works by hitting the status endpoint."""
        url = f"{self.base_url}/api-keys"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=self._headers())
                return response.status_code == 200
        except (httpx.HTTPStatusError, httpx.ConnectError):
            return False


def _extract_instagram(item: dict[str, Any]) -> str:
    """Try to extract Instagram handle from a lead item."""
    # Direct field
    handle = item.get("instagram") or item.get("instagram_handle") or ""
    if handle:
        return handle.lstrip("@")

    # From social links
    socials = item.get("socialLinks") or item.get("social_links") or {}
    if isinstance(socials, dict):
        ig = socials.get("instagram", "")
        if ig:
            # Extract handle from URL
            ig = ig.rstrip("/").split("/")[-1]
            return ig.lstrip("@")

    return ""
