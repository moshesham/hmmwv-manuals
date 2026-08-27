"""
ingestion/parser.py

Parses a single chapter markdown file into a list of RawBlock objects.
Handles:
  - Table-of-contents detection and exclusion
  - Anchor-based section heading detection
  - Safety block detection (WARNING / CAUTION / NOTE variants)
  - INITIAL SETUP / FOLLOW-ON TASKS boundary markers
  - Numbered step detection
  - Image reference extraction
  - Cross-reference string extraction
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------
BLOCK_TOC = "toc"
BLOCK_TASK = "task"
BLOCK_SECTION = "section"
BLOCK_TROUBLESHOOTING = "troubleshooting"
BLOCK_SAFETY = "safety"
BLOCK_PROSE = "prose"
BLOCK_SKIP = "skip"

# ---------------------------------------------------------------------------
# Safety keyword regexes (case-insensitive, tolerant of OCR dot noise)
# ---------------------------------------------------------------------------
_SAFETY_RE = re.compile(
    r"^#{1,4}\s*[.]*\s*(warning|caution|note)[.]*\s*$",
    re.IGNORECASE,
)
_SAFETY_INLINE_RE = re.compile(
    r"^\*{0,2}(WARNING|CAUTION|NOTE)\*{0,2}\s*$",
)

# Task heading: ### X-Y. Title  (also X-YY, X-YY-Z, etc.)
_TASK_HEADING_RE = re.compile(
    r"^(#{1,4})\s+(\d+[-–]\d+[a-z]?(?:\.\d+)?)[.\s]+(.+)$",
    re.IGNORECASE,
)

# Chapter / section heading (no numeric task prefix)
_SECTION_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")

# Anchor tag: <a name="X-Y">
_ANCHOR_RE = re.compile(r'<a\s+name=["\']([^"\']+)["\']', re.IGNORECASE)

# TOC table row: | [X-Y](#X-Y) | Description |
_TOC_ROW_RE = re.compile(r"^\|\s*\[")

# Image reference: ![...](path)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

# Cross-reference: TM 9-2320-280-XX or similar
_XREF_RE = re.compile(
    r"\bTM\s+\d[\d-]+(?:\s+\w+)?"
    r"|\bparagraph\s+\d[\d.-]+"
    r"|\btask\s+\d+-\d+\b",
    re.IGNORECASE,
)

# Numbered step patterns: (1), a., 1.
_STEP_RE = re.compile(r"^\s*(?:\(\d+\)|\d+\.|[a-h]\.)\s+")

# INITIAL SETUP / FOLLOW-ON TASKS markers
_INITIAL_SETUP_RE = re.compile(r"INITIAL\s+SETUP", re.IGNORECASE)
_FOLLOW_ON_RE = re.compile(r"FOLLOW.ON\s+TASKS?", re.IGNORECASE)

# Troubleshooting section keywords
_TROUBLE_SECTION_KEYWORDS = re.compile(
    r"troubleshooting|startability|compression|electrical\s+test|cooling\s+test"
    r"|lubrication\s+test|fuel\s+system|air\s+intake|brake\s+system"
    r"|steering\s+system|drivetrain|alternator\s+test|battery\s+circuit"
    r"|instrument\s+test|light\s+test|transmission\s+test",
    re.IGNORECASE,
)


@dataclass
class RawBlock:
    block_type: str            # toc | task | section | troubleshooting | safety | prose | skip
    anchor: Optional[str]
    heading: Optional[str]
    heading_level: int         # 1-4, 0 if no heading
    task_id: Optional[str]     # e.g. "2-14"
    safety_type: Optional[str] # warning | caution | note
    body_lines: list[str]
    line_start: int
    line_end: int
    source_path: str
    image_refs: list[str] = field(default_factory=list)
    cross_refs: list[str] = field(default_factory=list)
    has_initial_setup: bool = False
    has_follow_on: bool = False
    steps: list[str] = field(default_factory=list)
    in_troubleshooting_section: bool = False


def _detect_safety_type(line: str) -> Optional[str]:
    m = _SAFETY_RE.match(line.strip())
    if m:
        return m.group(1).lower()
    m2 = _SAFETY_INLINE_RE.match(line.strip())
    if m2:
        return m2.group(1).lower()
    return None


def _is_toc_block(lines: list[str]) -> bool:
    """Returns True if the block looks like a markdown table of contents."""
    table_lines = sum(1 for l in lines if _TOC_ROW_RE.match(l))
    return table_lines >= 3


def parse_chapter(path: Path, manual_id: str, manual_role: str) -> list[RawBlock]:
    """
    Parse a chapter markdown file into RawBlock objects.
    Blocks are delimited by anchor tags and heading boundaries.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks: list[RawBlock] = []

    current_anchor: Optional[str] = None
    current_heading: Optional[str] = None
    current_heading_level: int = 0
    current_task_id: Optional[str] = None
    current_block_type: str = BLOCK_PROSE
    current_safety_type: Optional[str] = None
    current_body: list[str] = []
    block_start: int = 0
    in_troubleshooting_section: bool = False
    in_toc: bool = False

    def _flush(end_line: int):
        nonlocal current_anchor, current_heading, current_heading_level
        nonlocal current_task_id, current_block_type, current_safety_type
        nonlocal current_body, block_start, in_toc

        if not current_body and current_heading is None:
            return

        # Detect TOC block
        block_type = current_block_type
        if in_toc or _is_toc_block(current_body):
            block_type = BLOCK_TOC
            in_toc = False

        # Extract image refs and cross-refs from body
        body_text = "\n".join(current_body)
        image_refs = _IMAGE_RE.findall(body_text)
        cross_refs = _XREF_RE.findall(body_text)
        has_initial_setup = bool(_INITIAL_SETUP_RE.search(body_text))
        has_follow_on = bool(_FOLLOW_ON_RE.search(body_text))
        steps = [l for l in current_body if _STEP_RE.match(l)]

        blocks.append(RawBlock(
            block_type=block_type,
            anchor=current_anchor,
            heading=current_heading,
            heading_level=current_heading_level,
            task_id=current_task_id,
            safety_type=current_safety_type,
            body_lines=list(current_body),
            line_start=block_start,
            line_end=end_line,
            source_path=str(path),
            image_refs=image_refs,
            cross_refs=cross_refs,
            has_initial_setup=has_initial_setup,
            has_follow_on=has_follow_on,
            steps=steps,
            in_troubleshooting_section=in_troubleshooting_section,
        ))

        # Reset
        current_anchor = None
        current_heading = None
        current_heading_level = 0
        current_task_id = None
        current_block_type = BLOCK_PROSE
        current_safety_type = None
        current_body = []
        block_start = end_line

    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect anchor tag (may appear alone or inline)
        anchor_m = _ANCHOR_RE.search(line)
        if anchor_m:
            new_anchor = anchor_m.group(1)
            # If line is only an anchor tag, start a new block
            stripped = _ANCHOR_RE.sub("", line).strip()
            if not stripped:
                _flush(i)
                current_anchor = new_anchor
                block_start = i
                i += 1
                continue
            else:
                # Anchor inline with heading — flush previous, continue with this line
                _flush(i)
                current_anchor = new_anchor
                block_start = i
                # Fall through to process heading on same line

        # Detect safety heading
        safety_type = _detect_safety_type(line)
        if safety_type:
            # If we are inside an open task block, keep safety inline rather than
            # flushing — this prevents the task's step content from being cut off.
            if current_block_type == BLOCK_TASK:
                current_body.append(line)
                i += 1
                # Absorb the safety body lines into the task block
                while i < len(lines):
                    next_line = lines[i]
                    if next_line.startswith("#") or _ANCHOR_RE.search(next_line):
                        break
                    if _detect_safety_type(next_line):
                        break
                    current_body.append(next_line)
                    i += 1
                continue
            # Outside a task — flush previous block and emit a standalone safety block
            _flush(i)
            current_block_type = BLOCK_SAFETY
            current_safety_type = safety_type
            current_heading = line.strip()
            current_heading_level = line.count("#") if line.startswith("#") else 0
            block_start = i
            i += 1
            # Collect safety body until next heading
            while i < len(lines):
                next_line = lines[i]
                if next_line.startswith("#") or _ANCHOR_RE.search(next_line):
                    break
                if _detect_safety_type(next_line):
                    break
                current_body.append(next_line)
                i += 1
            _flush(i)
            continue

        # Detect task heading (### X-Y. Title)
        task_m = _TASK_HEADING_RE.match(line)
        if task_m:
            _flush(i)
            level = len(task_m.group(1))
            task_id = task_m.group(2)
            heading_text = task_m.group(3).strip()
            heading_full = f"{task_id}. {heading_text}"

            # Classify as troubleshooting if section context or heading keywords match
            btype = BLOCK_TROUBLESHOOTING if (
                in_troubleshooting_section or bool(_TROUBLE_SECTION_KEYWORDS.search(heading_full))
            ) else BLOCK_TASK

            current_heading = heading_full
            current_heading_level = level
            current_task_id = task_id
            current_block_type = btype
            block_start = i
            i += 1
            continue

        # Detect generic section heading
        sec_m = _SECTION_HEADING_RE.match(line)
        if sec_m:
            heading_text = sec_m.group(2).strip()
            level = len(sec_m.group(1))

            # Update troubleshooting section flag
            if _TROUBLE_SECTION_KEYWORDS.search(heading_text):
                in_troubleshooting_section = True
            elif level <= 2:
                # A high-level heading resets the troubleshooting context
                in_troubleshooting_section = False

            # Flush if this is a substantial heading (level 1-3)
            if level <= 3 and heading_text:
                _flush(i)
                current_heading = heading_text
                current_heading_level = level
                current_block_type = BLOCK_SECTION
                block_start = i

            else:
                # Low-level heading (####) stays inside current block
                current_body.append(line)

            i += 1
            continue

        # TOC detection: if we see many table rows at the start of file
        if _TOC_ROW_RE.match(line) and i < 80:
            in_toc = True

        current_body.append(line)
        i += 1

    _flush(len(lines))
    return blocks
