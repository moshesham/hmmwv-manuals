"""
ingestion/loader.py

Discovers and loads source files for the 4 MVP manuals.
Returns a stable, sorted list of (manual_id, manual_role, chapter_path, meta) tuples.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


MVP_MANUAL_IDS = [
    "TM-9-2320-280-20-1",
    "TM-9-2320-280-20-2",
    "TM-9-2320-280-20-3",
    "tm-9-2320-280-10",
]

MANUAL_ROLE_MAP = {
    "TM-9-2320-280-20-1": "maintenance",
    "TM-9-2320-280-20-2": "maintenance",
    "TM-9-2320-280-20-3": "maintenance",
    "tm-9-2320-280-10": "operator",
}


@dataclass
class ManualMeta:
    manual_id: str
    manual_role: str
    title: Optional[str] = None
    publication_date: Optional[str] = None
    extra: dict = None

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


@dataclass
class SourceRecord:
    manual_id: str
    manual_role: str
    chapter_path: Path
    chapter_name: str
    meta: ManualMeta


def _load_meta(meta_path: Path, manual_id: str, manual_role: str) -> ManualMeta:
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return ManualMeta(
                manual_id=manual_id,
                manual_role=manual_role,
                title=data.get("title"),
                publication_date=data.get("date") or data.get("publication_date"),
                extra=data,
            )
        except (json.JSONDecodeError, KeyError):
            pass
    return ManualMeta(manual_id=manual_id, manual_role=manual_role)


def discover_sources(corpus_root: Path, manual_ids: list[str] = MVP_MANUAL_IDS) -> list[SourceRecord]:
    """
    Walk corpus_root for the given manual directory names.
    Returns a deterministically sorted list of SourceRecord objects.
    """
    records: list[SourceRecord] = []

    for manual_id in manual_ids:
        manual_dir = corpus_root / manual_id
        if not manual_dir.is_dir():
            print(f"  [WARN] Manual directory not found: {manual_dir}")
            continue

        manual_role = MANUAL_ROLE_MAP.get(manual_id, "other")

        # Try to find a meta JSON — prefer the one matching the directory name
        meta_candidates = [
            manual_dir / f"{manual_id}_meta.json",
            manual_dir / f"{manual_id.lower()}_meta.json",
        ]
        meta_path = next((p for p in meta_candidates if p.exists()), meta_candidates[0])
        meta = _load_meta(meta_path, manual_id, manual_role)

        # Collect chapter markdown files; exclude TOC / full-manual rollup files
        chapter_files = sorted(
            p for p in manual_dir.glob("*.md")
            if p.stem.lower().startswith("chapter")
            or p.stem.lower().startswith("appendix")
        )

        # Also include standalone section files (or the main rollup file) if no chapter files found
        if not chapter_files:
            chapter_files = sorted(
                p for p in manual_dir.glob("*.md")
                if not p.stem.lower().endswith("_meta")
            )

        for chapter_path in chapter_files:
            records.append(
                SourceRecord(
                    manual_id=manual_id,
                    manual_role=manual_role,
                    chapter_path=chapter_path,
                    chapter_name=chapter_path.stem,
                    meta=meta,
                )
            )

    return records
