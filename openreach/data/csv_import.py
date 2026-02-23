"""CSV import/export for standalone mode."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from openreach.data.store import DataStore

logger = logging.getLogger(__name__)

# Supported CSV column name mappings
COLUMN_ALIASES: dict[str, str] = {
    "name": "name",
    "business_name": "name",
    "business": "name",
    "company": "name",
    "instagram": "instagram_handle",
    "instagram_handle": "instagram_handle",
    "ig_handle": "instagram_handle",
    "ig": "instagram_handle",
    "handle": "instagram_handle",
    "type": "business_type",
    "business_type": "business_type",
    "category": "business_type",
    "industry": "business_type",
    "location": "location",
    "address": "location",
    "city": "location",
    "rating": "rating",
    "stars": "rating",
    "reviews": "review_count",
    "review_count": "review_count",
    "num_reviews": "review_count",
    "website": "website",
    "url": "website",
    "site": "website",
    "notes": "notes",
    "note": "notes",
    "pain_points": "pain_points",
    "pain": "pain_points",
    "issues": "pain_points",
    "offer": "offer_context",
    "offer_context": "offer_context",
    "pitch": "offer_context",
}


def import_from_csv(filepath: str | Path, db_path: str = "") -> int:
    """Import leads from a CSV file into the local database.

    Supports flexible column naming via COLUMN_ALIASES.

    Args:
        filepath: Path to the CSV file
        db_path: Optional database path override

    Returns:
        Number of leads imported
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")

    store = DataStore(db_path)
    leads: list[dict[str, Any]] = []

    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise ValueError("CSV file has no headers")

        # Map CSV columns to our field names
        column_map: dict[str, str] = {}
        for col in reader.fieldnames:
            normalized = col.strip().lower().replace(" ", "_").replace("-", "_")
            if normalized in COLUMN_ALIASES:
                column_map[col] = COLUMN_ALIASES[normalized]
            else:
                logger.debug("Unmapped CSV column: %s", col)

        if "instagram_handle" not in column_map.values():
            logger.warning(
                "No Instagram handle column found. "
                "Expected one of: instagram, instagram_handle, ig_handle, ig, handle"
            )

        for row in reader:
            lead_data: dict[str, Any] = {"source": "csv"}
            for csv_col, our_field in column_map.items():
                value = row.get(csv_col, "").strip()
                if not value:
                    continue

                if our_field == "rating":
                    try:
                        lead_data[our_field] = float(value)
                    except ValueError:
                        pass
                elif our_field == "review_count":
                    try:
                        lead_data[our_field] = int(value.replace(",", ""))
                    except ValueError:
                        pass
                else:
                    lead_data[our_field] = value

            # Skip rows without a name or handle
            if not lead_data.get("name") and not lead_data.get("instagram_handle"):
                continue

            leads.append(lead_data)

    count = store.add_leads(leads)
    logger.info("Imported %d leads from %s", count, filepath)
    return count


def export_to_csv(filepath: str | Path, db_path: str = "") -> int:
    """Export leads from the local database to a CSV file.

    Args:
        filepath: Output CSV file path
        db_path: Optional database path override

    Returns:
        Number of leads exported
    """
    filepath = Path(filepath)
    store = DataStore(db_path)
    leads = store.get_leads(limit=100000)

    if not leads:
        logger.warning("No leads to export")
        return 0

    fieldnames = [
        "name",
        "instagram_handle",
        "business_type",
        "location",
        "rating",
        "review_count",
        "website",
        "notes",
        "pain_points",
        "offer_context",
        "source",
    ]

    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)

    logger.info("Exported %d leads to %s", len(leads), filepath)
    return len(leads)
