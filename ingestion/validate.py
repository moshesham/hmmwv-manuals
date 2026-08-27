"""
ingestion/validate.py

Validates a content unit dict against the canonical JSON schema.
Uses jsonschema for validation. Falls back gracefully if schema file is missing.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


@lru_cache(maxsize=1)
def _load_schema(schema_path: str) -> dict[str, Any]:
    return json.loads(Path(schema_path).read_text(encoding="utf-8"))


def validate_unit(
    unit_dict: dict[str, Any],
    schema_path: Path,
) -> tuple[bool, list[str]]:
    """
    Validate a content unit dict against the JSON schema.
    Returns (is_valid, [error_message, ...]).
    """
    if not _HAS_JSONSCHEMA:
        return True, []

    if not schema_path.exists():
        return True, [f"Schema file not found at {schema_path}; skipping validation."]

    schema = _load_schema(str(schema_path))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(unit_dict), key=lambda e: list(e.path))
    if errors:
        msgs = [f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors[:5]]
        return False, msgs
    return True, []
