"""
ingestion/chunker.py

Assembles ContentUnit objects from parsed RawBlocks.

Rules:
- procedure_task: starts at a BLOCK_TASK anchor; ends before next same-level
  task/section; safety blocks, INITIAL SETUP, steps, FOLLOW-ON TASKS all fold in.
- troubleshooting_entry: each BLOCK_TROUBLESHOOTING block becomes one unit with
  inferred yes/no branches.
- diagnostic_flow: sequences of troubleshooting_entry units under a shared
  parent section heading are promoted to a diagnostic_flow container with linked
  diagnostic_flow_node children.
- safety_summary: free-standing BLOCK_SAFETY not attached to any task.
- reference_section: BLOCK_SECTION blocks that are not tasks or troubleshooting.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Optional

from ingestion.models import (
    SCHEMA_VERSION,
    ContentUnit,
    CrossRef,
    DiagnosticEdge,
    DiagnosticFlowBlock,
    ModeMetadata,
    ProcedureBlock,
    ProcedureStep,
    Provenance,
    SafetyBlock,
    TaxonomyEntry,
    TroubleshootingBlock,
    TroubleshootingBranch,
    generate_content_id,
)
from ingestion.parser import (
    BLOCK_SAFETY,
    BLOCK_SECTION,
    BLOCK_TASK,
    BLOCK_TOC,
    BLOCK_TROUBLESHOOTING,
    RawBlock,
    _detect_safety_type,
)

# Max plain-text length before a task is split into procedure_step_group sub-units
MAX_TASK_CHARS = 8_000

# Patterns for troubleshooting branch detection
_YES_RE = re.compile(r"\bYES\b|→\s*YES|->\s*YES", re.IGNORECASE)
_NO_RE = re.compile(r"\bNO\b|→\s*NO|->\s*NO", re.IGNORECASE)
_GOTO_RE = re.compile(r"go\s+to\s+(?:step\s+)?(\d+[-–]\d+\w*)", re.IGNORECASE)

# TM cross-ref
_TM_XREF_RE = re.compile(r"TM\s+([\d-]+(?:/\d+)?)", re.IGNORECASE)
_PARA_XREF_RE = re.compile(r"paragraph\s+(\d[\d.-]+)", re.IGNORECASE)
_TASK_XREF_RE = re.compile(r"\btask\s+(\d+-\d+\w*)\b", re.IGNORECASE)

# Risk keywords for safety association check
_RISK_KEYWORDS_RE = re.compile(
    r"voltage|current|battery|flammable|solvent|pressur|lift|jack|fuel|acid|explosion",
    re.IGNORECASE,
)

# Maintenance mode indicators
_MAINT_RE = re.compile(r"replace|remove|install|repair|adjust|torque|disassemble", re.IGNORECASE)
_OPERATOR_RE = re.compile(r"operator|driver|pmcs|before\s+you\s+start", re.IGNORECASE)


def _extract_inline_safety(body_lines: list[str]) -> tuple[list[SafetyBlock], list[SafetyBlock], list[SafetyBlock]]:
    """
    Scan a task block's body lines for inline safety headers (### Warning / ### Note / etc.)
    that were kept in-body by the parser (fix 6). Returns (warnings, cautions, notes).
    The function collects the text following each safety header until the next safety header
    or a hard boundary line.
    """
    warns: list[SafetyBlock] = []
    cauts: list[SafetyBlock] = []
    nts: list[SafetyBlock] = []

    i = 0
    while i < len(body_lines):
        stype = _detect_safety_type(body_lines[i])
        if stype:
            # Collect the safety body lines
            safety_lines: list[str] = []
            i += 1
            while i < len(body_lines):
                if _detect_safety_type(body_lines[i]):
                    break
                if body_lines[i].startswith("#"):
                    break
                safety_lines.append(body_lines[i])
                i += 1
            text = _plain_text(safety_lines)
            block = SafetyBlock(safety_type=stype, text=text)
            if stype == "warning":
                warns.append(block)
            elif stype == "caution":
                cauts.append(block)
            else:
                nts.append(block)
        else:
            i += 1

    return warns, cauts, nts


def _plain_text(lines: list[str]) -> str:
    """Strip markdown formatting for plain-text embedding."""
    text = "\n".join(lines)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)   # images
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)       # code
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _infer_mode(heading: str, body: str) -> ModeMetadata:
    maint_score = len(_MAINT_RE.findall(heading + " " + body[:500]))
    op_score = len(_OPERATOR_RE.findall(heading + " " + body[:500]))
    if maint_score > op_score:
        detected = "maintenance"
        conf = min(0.5 + maint_score * 0.1, 0.95)
    elif op_score > maint_score:
        detected = "operator"
        conf = min(0.5 + op_score * 0.1, 0.95)
    else:
        detected = "mixed_or_uncertain"
        conf = 0.4
    return ModeMetadata(
        detected_mode=detected,
        selected_mode=detected,
        selection_source="inferred",
        confidence_score=round(conf, 2),
        override_allowed=True,
    )


def _extract_cross_refs(cross_ref_strings: list[str], source_path: str) -> list[CrossRef]:
    refs: list[CrossRef] = []
    seen: set[str] = set()
    for s in cross_ref_strings:
        if s in seen:
            continue
        seen.add(s)
        tm_m = _TM_XREF_RE.search(s)
        para_m = _PARA_XREF_RE.search(s)
        task_m = _TASK_XREF_RE.search(s)
        refs.append(CrossRef(
            source_string=s,
            target_manual=f"TM-{tm_m.group(1)}" if tm_m else None,
            target_anchor=task_m.group(1) if task_m else None,
            target_section=para_m.group(1) if para_m else None,
        ))
    return refs


def _extract_steps(lines: list[str]) -> list[ProcedureStep]:
    """Parse numbered/lettered step lines into ProcedureStep objects."""
    steps: list[ProcedureStep] = []
    current_num: Optional[str] = None
    current_text: list[str] = []
    sub_steps: list[str] = []

    step_re = re.compile(r"^\s*(\(\d+\)|\d+\.|[a-h]\.)\s+(.*)")
    sub_re = re.compile(r"^\s{4,}(\(\w+\)|[a-h]\.)\s+(.*)")

    for line in lines:
        sub_m = sub_re.match(line)
        step_m = step_re.match(line)
        if step_m and not sub_m:
            if current_num is not None:
                steps.append(ProcedureStep(
                    step_number=current_num,
                    text=" ".join(current_text).strip(),
                    sub_steps=list(sub_steps),
                ))
            current_num = step_m.group(1).strip(".()")
            current_text = [step_m.group(2)]
            sub_steps = []
        elif sub_m and current_num is not None:
            sub_steps.append(sub_m.group(2))
        elif current_num is not None:
            current_text.append(line.strip())

    if current_num is not None:
        steps.append(ProcedureStep(
            step_number=current_num,
            text=" ".join(current_text).strip(),
            sub_steps=list(sub_steps),
        ))
    return steps


def _build_procedure(block: RawBlock) -> Optional[ProcedureBlock]:
    body = "\n".join(block.body_lines)
    if not (block.has_initial_setup or block.steps or block.has_follow_on):
        return None

    initial_setup: list[str] = []
    follow_on: list[str] = []
    step_lines: list[str] = []

    state = "pre"
    for line in block.body_lines:
        if re.search(r"INITIAL\s+SETUP", line, re.IGNORECASE):
            state = "initial"
            continue
        if re.search(r"FOLLOW.ON\s+TASKS?", line, re.IGNORECASE):
            state = "followon"
            continue
        if state == "initial" and line.strip():
            if re.match(r"^\s*(\(\d+\)|\d+\.|[a-h]\.)\s+", line):
                state = "steps"
                step_lines.append(line)
            else:
                initial_setup.append(line.strip())
        elif state == "steps":
            if re.search(r"FOLLOW.ON\s+TASKS?", line, re.IGNORECASE):
                state = "followon"
            else:
                step_lines.append(line)
        elif state == "followon" and line.strip():
            follow_on.append(line.strip())
        elif state == "pre":
            if re.match(r"^\s*(\(\d+\)|\d+\.|[a-h]\.)\s+", line):
                state = "steps"
                step_lines.append(line)

    steps = _extract_steps(step_lines)
    return ProcedureBlock(
        initial_setup=[s for s in initial_setup if s],
        steps=steps,
        follow_on_tasks=[s for s in follow_on if s],
    )


def _infer_branches(block: RawBlock) -> list[TroubleshootingBranch]:
    branches: list[TroubleshootingBranch] = []
    body = "\n".join(block.body_lines)

    # YES branch
    if _YES_RE.search(body):
        goto_m = _GOTO_RE.search(body[body.lower().find("yes"):]) if "yes" in body.lower() else None
        branches.append(TroubleshootingBranch(
            condition="yes",
            target_anchor=goto_m.group(1) if goto_m else None,
            target_text=goto_m.group(0) if goto_m else None,
        ))
    # NO branch
    if _NO_RE.search(body):
        goto_m = _GOTO_RE.search(body[body.lower().find("no"):]) if "no" in body.lower() else None
        branches.append(TroubleshootingBranch(
            condition="no",
            target_anchor=goto_m.group(1) if goto_m else None,
            target_text=goto_m.group(0) if goto_m else None,
        ))
    # If neither, default continue edge
    if not branches:
        branches.append(TroubleshootingBranch(
            condition="continue",
            target_anchor=None,
            target_text=None,
        ))
    return branches


def _make_provenance(block: RawBlock, excerpt_limit: int = 500) -> Provenance:
    body_text = "\n".join(block.body_lines)
    excerpt = body_text[:excerpt_limit].replace("\n", " ").strip()
    return Provenance(
        source_path=block.source_path,
        anchor=block.anchor,
        line_start=block.line_start,
        line_end=block.line_end,
        excerpt=excerpt,
        parser_confidence="high" if block.anchor else "medium",
    )


def _make_taxonomy(block: RawBlock) -> TaxonomyEntry:
    """Minimal taxonomy — Stage 3 enrichment fills this in later."""
    return TaxonomyEntry()


def build_content_units(
    raw_blocks: list[RawBlock],
    manual_id: str,
    manual_role: str,
    source_path: str,
    chapter_name: str,
    chunk_counter: Optional[dict[str, int]] = None,
) -> list[ContentUnit]:
    units: list[ContentUnit] = []
    # Allow caller to pass in a shared counter so IDs remain unique across chapters
    # within the same manual.  If not provided, create a local one (backwards compat).
    if chunk_counter is None:
        chunk_counter = {}

    # Group consecutive troubleshooting blocks for diagnostic_flow promotion
    trouble_groups: list[list[tuple[int, RawBlock]]] = []
    current_trouble_group: list[tuple[int, RawBlock]] = []
    current_section_heading: Optional[str] = None

    def _emit_trouble_group(group: list[tuple[int, RawBlock]], section_heading: Optional[str]):
        """Convert a group of troubleshooting blocks into a diagnostic_flow container."""
        if len(group) < 2:
            return  # Single troubleshooting entries remain as standalone units
        flow_id = generate_content_id(manual_id, f"flow_{group[0][1].anchor or group[0][0]}", 0)
        node_ids: list[str] = []
        edges: list[DiagnosticEdge] = []

        for idx, (pos, blk) in enumerate(group):
            node_id = generate_content_id(manual_id, blk.anchor or f"node_{pos}", pos)
            node_ids.append(node_id)
            for branch in _infer_branches(blk):
                if idx + 1 < len(group):
                    target_node = generate_content_id(
                        manual_id,
                        group[idx + 1][1].anchor or f"node_{group[idx+1][0]}",
                        group[idx + 1][0],
                    )
                else:
                    target_node = branch.target_anchor or "end"
                edges.append(DiagnosticEdge(
                    from_node=node_id,
                    to_node=target_node,
                    condition=branch.condition,
                ))

        flow_block = DiagnosticFlowBlock(
            flow_id=flow_id,
            entry_node_ids=[node_ids[0]] if node_ids else [],
            node_ids=node_ids,
            node_texts={
                generate_content_id(manual_id, blk.anchor or f"node_{pos}", pos):
                    _plain_text(blk.body_lines)[:300] or (blk.heading or "")
                for pos, blk in group
            },
            edges=edges,
            support_panel_ids=[],
        )

        title = section_heading or f"Diagnostic Flow — {manual_id}"
        all_body = []
        all_cross_refs = []
        all_images = []
        for _, blk in group:
            all_body.extend(blk.body_lines)
            all_cross_refs.extend(blk.cross_refs)
            all_images.extend(blk.image_refs)

        md_text = "\n".join(all_body)
        plain_text = _plain_text(all_body)
        prov = _make_provenance(group[0][1])
        mode = _infer_mode(title, plain_text)

        content_id = generate_content_id(manual_id, f"flow_{group[0][1].anchor or group[0][0]}", 0)
        chunk_counter[content_id] = chunk_counter.get(content_id, 0) + 1

        units.append(ContentUnit(
            schema_version=SCHEMA_VERSION,
            content_id=content_id,
            manual_id=manual_id,
            manual_role=manual_role,
            mode=mode,
            source=prov,
            unit_type="diagnostic_flow",
            title=title,
            text_markdown=md_text[:MAX_TASK_CHARS],
            text_plain=plain_text[:MAX_TASK_CHARS],
            provenance=prov,
            taxonomy=_make_taxonomy(group[0][1]),
            chapter=chapter_name,
            cross_manual_refs=_extract_cross_refs(all_cross_refs, source_path),
            image_refs=list(set(all_images)),
            diagnostic_flow=flow_block,
        ))

        # Also emit individual diagnostic_flow_node units
        for pos, blk in group:
            node_id = generate_content_id(manual_id, blk.anchor or f"node_{pos}", pos)
            node_md = "\n".join(blk.body_lines)
            node_plain = _plain_text(blk.body_lines)
            node_prov = _make_provenance(blk)
            trouble = TroubleshootingBlock(
                symptom=blk.heading,
                question=blk.heading,
                branches=_infer_branches(blk),
            )
            units.append(ContentUnit(
                schema_version=SCHEMA_VERSION,
                content_id=node_id,
                manual_id=manual_id,
                manual_role=manual_role,
                mode=_infer_mode(blk.heading or "", node_plain),
                source=node_prov,
                unit_type="diagnostic_flow_node",
                title=blk.heading or f"Step {blk.task_id}",
                text_markdown=node_md[:MAX_TASK_CHARS],
                text_plain=node_plain[:MAX_TASK_CHARS],
                provenance=node_prov,
                taxonomy=_make_taxonomy(blk),
                chapter=chapter_name,
                cross_manual_refs=_extract_cross_refs(blk.cross_refs, source_path),
                image_refs=blk.image_refs,
                troubleshooting=trouble,
                parent_flow_id=flow_id,
                node_type="check" if blk.steps else "question",
            ))

    # Pending safety blocks to attach to next task
    pending_safety: list[tuple[str, RawBlock]] = []

    for pos, block in enumerate(raw_blocks):
        # Skip TOC and empty blocks
        if block.block_type == BLOCK_TOC:
            continue
        body_text = "\n".join(block.body_lines).strip()
        if not body_text and not block.heading:
            continue

        if block.block_type == BLOCK_SAFETY:
            pending_safety.append((block.safety_type or "note", block))
            continue

        if block.block_type == BLOCK_TROUBLESHOOTING:
            current_trouble_group.append((pos, block))
            continue
        else:
            # Flush any pending trouble group
            if current_trouble_group:
                _emit_trouble_group(current_trouble_group, current_section_heading)
                current_trouble_group = []
            if block.block_type == BLOCK_SECTION:
                current_section_heading = block.heading

        # --- Build content unit for task / section ---
        if block.block_type in (BLOCK_TASK, BLOCK_SECTION):
            title = block.heading or f"Section {pos}"
            unit_type = "procedure_task" if block.block_type == BLOCK_TASK else "reference_section"
            md_text = "\n".join(block.body_lines)
            plain = _plain_text(block.body_lines)
            prov = _make_provenance(block)
            mode = _infer_mode(title, plain)

            # Attach pending safety blocks (standalone BLOCK_SAFETY blocks preceding this task)
            warns = [SafetyBlock(safety_type="warning", text=_plain_text(b.body_lines), source_line=b.line_start)
                     for stype, b in pending_safety if stype == "warning"]
            cauts = [SafetyBlock(safety_type="caution", text=_plain_text(b.body_lines), source_line=b.line_start)
                     for stype, b in pending_safety if stype == "caution"]
            nts = [SafetyBlock(safety_type="note", text=_plain_text(b.body_lines), source_line=b.line_start)
                   for stype, b in pending_safety if stype == "note"]
            pending_safety = []

            # Also extract inline safety blocks folded into this task's body_lines (fix 6)
            if block.block_type == BLOCK_TASK:
                inline_warns, inline_cauts, inline_nts = _extract_inline_safety(block.body_lines)
                warns.extend(inline_warns)
                cauts.extend(inline_cauts)
                nts.extend(inline_nts)

            procedure = _build_procedure(block) if block.block_type == BLOCK_TASK else None
            content_id = generate_content_id(
                manual_id,
                block.anchor or block.task_id,
                chunk_counter.get(block.anchor or "", 0),
            )
            chunk_counter[block.anchor or ""] = chunk_counter.get(block.anchor or "", 0) + 1

            units.append(ContentUnit(
                schema_version=SCHEMA_VERSION,
                content_id=content_id,
                manual_id=manual_id,
                manual_role=manual_role,
                mode=mode,
                source=prov,
                unit_type=unit_type,
                title=title,
                text_markdown=md_text[:MAX_TASK_CHARS],
                text_plain=plain[:MAX_TASK_CHARS],
                provenance=prov,
                taxonomy=_make_taxonomy(block),
                chapter=chapter_name,
                warnings=warns,
                cautions=cauts,
                notes=nts,
                procedure=procedure,
                cross_manual_refs=_extract_cross_refs(block.cross_refs, source_path),
                image_refs=block.image_refs,
            ))

    # Flush any remaining trouble group
    if current_trouble_group:
        _emit_trouble_group(current_trouble_group, current_section_heading)

    # Flush any remaining free-standing safety blocks
    for stype, block in pending_safety:
        title = block.heading or f"Safety — {stype.capitalize()}"
        prov = _make_provenance(block)
        content_id = generate_content_id(manual_id, block.anchor, pos)
        units.append(ContentUnit(
            schema_version=SCHEMA_VERSION,
            content_id=content_id,
            manual_id=manual_id,
            manual_role=manual_role,
            mode=ModeMetadata(),
            source=prov,
            unit_type="safety_summary",
            title=title,
            text_markdown="\n".join(block.body_lines),
            text_plain=_plain_text(block.body_lines),
            provenance=prov,
            taxonomy=_make_taxonomy(block),
            chapter=chapter_name,
            warnings=[SafetyBlock(safety_type=stype, text=_plain_text(block.body_lines))],
        ))

    return units
