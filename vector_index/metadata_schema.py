"""
vector_index/metadata_schema.py

Defines the flat metadata dict stored in ChromaDB per content unit.
ChromaDB requires flat dicts with str/int/float/bool values.
Booleans are stored as ints (0/1) for ChromaDB compatibility.
"""
from __future__ import annotations

from typing import Any

CHROMADB_COLLECTION = "hmmwv_units"


def unit_to_metadata(unit_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Extract a flat ChromaDB-compatible metadata dict from a content unit dict.
    """
    tax = unit_dict.get("taxonomy", {})
    prov = unit_dict.get("provenance", {})
    source = unit_dict.get("source", {})
    mode = unit_dict.get("mode", {})

    has_warnings = int(bool(unit_dict.get("warnings")))
    has_cautions = int(bool(unit_dict.get("cautions")))
    has_steps = int(bool(
        unit_dict.get("procedure", {}).get("steps") if unit_dict.get("procedure") else False
    ))

    return {
        "content_id": unit_dict.get("content_id", ""),
        "manual_id": unit_dict.get("manual_id", ""),
        "manual_role": unit_dict.get("manual_role", ""),
        "unit_type": unit_dict.get("unit_type", ""),
        "chapter": unit_dict.get("chapter") or "",
        "subsystem": tax.get("subsystem") or "",
        "maintenance_category": tax.get("maintenance_category") or "",
        "has_warnings": has_warnings,
        "has_cautions": has_cautions,
        "has_steps": has_steps,
        "mode_detected": mode.get("detected_mode", "mixed_or_uncertain"),
        "mode_confidence": float(mode.get("confidence_score", 0.5)),
        "source_path": source.get("path", ""),
        "anchor": source.get("anchor") or "",
        "title": unit_dict.get("title", "")[:200],
    }


def build_chroma_where(filters: dict[str, Any]) -> dict[str, Any] | None:
    """
    Convert a user-provided filter dict to a ChromaDB `where` clause.

    Supported filter keys:
        manual_id, manual_role, unit_type, chapter, subsystem,
        maintenance_category, has_warnings, has_cautions, has_steps,
        mode_detected

    Example:
        {"manual_role": "maintenance", "subsystem": "engine", "has_warnings": 1}
    """
    if not filters:
        return None

    conditions = []
    for key, value in filters.items():
        if key in ("has_warnings", "has_cautions", "has_steps"):
            conditions.append({key: {"$eq": int(value)}})
        elif isinstance(value, str):
            conditions.append({key: {"$eq": value}})
        else:
            conditions.append({key: {"$eq": value}})

    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}
