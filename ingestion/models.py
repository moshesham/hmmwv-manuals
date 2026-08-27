"""
ingestion/models.py

ContentUnit dataclass mirroring content-unit.schema.json v1.1.0.
Provides to_dict / from_dict helpers and a deterministic content_id generator.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

SCHEMA_VERSION = "1.1.0"


def generate_content_id(manual_id: str, anchor: Optional[str], chunk_index: int) -> str:
    """Produce a stable, slug-safe content ID."""
    base = f"{manual_id}:{anchor or 'noanc'}:{chunk_index}"
    slug = re.sub(r"[^A-Za-z0-9._:-]", "_", base)
    # Keep under 128 chars; append short hash to guarantee uniqueness on collision.
    if len(slug) > 100:
        h = hashlib.md5(slug.encode()).hexdigest()[:8]
        slug = slug[:92] + "_" + h
    return slug


# ---------------------------------------------------------------------------
# Safety block
# ---------------------------------------------------------------------------

@dataclass
class SafetyBlock:
    safety_type: str  # warning | caution | note
    text: str
    source_line: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Procedure structures
# ---------------------------------------------------------------------------

@dataclass
class ProcedureStep:
    step_number: str
    text: str
    sub_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcedureBlock:
    initial_setup: list[str] = field(default_factory=list)
    steps: list[ProcedureStep] = field(default_factory=list)
    follow_on_tasks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_setup": self.initial_setup,
            "steps": [s.to_dict() for s in self.steps],
            "follow_on_tasks": self.follow_on_tasks,
        }


# ---------------------------------------------------------------------------
# Troubleshooting structures
# ---------------------------------------------------------------------------

@dataclass
class TroubleshootingBranch:
    condition: str  # yes | no | pass | fail | continue | branch-to-reference
    target_anchor: Optional[str]
    target_text: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TroubleshootingBlock:
    symptom: Optional[str] = None
    question: Optional[str] = None
    branches: list[TroubleshootingBranch] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symptom": self.symptom,
            "question": self.question,
            "branches": [b.to_dict() for b in self.branches],
        }


# ---------------------------------------------------------------------------
# Diagnostic flow structures
# ---------------------------------------------------------------------------

@dataclass
class DiagnosticEdge:
    from_node: str
    to_node: str
    condition: str  # yes | no | pass | fail | continue | branch-to-reference

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiagnosticFlowBlock:
    flow_id: str
    entry_node_ids: list[str] = field(default_factory=list)
    node_ids: list[str] = field(default_factory=list)
    node_texts: dict[str, str] = field(default_factory=dict)  # node_id → heading/body text
    edges: list[DiagnosticEdge] = field(default_factory=list)
    support_panel_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "entry_node_ids": self.entry_node_ids,
            "node_ids": self.node_ids,
            "edges": [e.to_dict() for e in self.edges],
            "support_panel_ids": self.support_panel_ids,
        }


# ---------------------------------------------------------------------------
# Cross-reference
# ---------------------------------------------------------------------------

@dataclass
class CrossRef:
    source_string: str
    target_manual: Optional[str]
    target_anchor: Optional[str]
    target_section: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Mode metadata
# ---------------------------------------------------------------------------

@dataclass
class ModeMetadata:
    detected_mode: str = "mixed_or_uncertain"       # operator | maintenance | mixed_or_uncertain
    selected_mode: str = "mixed_or_uncertain"
    selection_source: str = "inferred"              # inferred | explicit | system_default | inherited
    confidence_score: float = 0.5
    persistence_threshold: float = 0.75
    override_allowed: bool = True
    automatic_persistence_allowed: bool = False
    requires_clarification: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

@dataclass
class Provenance:
    source_path: str
    anchor: Optional[str]
    line_start: int
    line_end: int
    excerpt: str
    heading: Optional[str] = None
    parser_confidence: str = "high"  # high | medium | low

    def to_dict(self) -> dict[str, Any]:
        """Schema-compliant provenance dict (excerpt + chunk_id + parser_confidence)."""
        chunk_id = f"{self.source_path}:{self.line_start}-{self.line_end}"
        return {
            "excerpt": self.excerpt,
            "chunk_id": chunk_id,
            "parser_confidence": self.parser_confidence,
        }

    def to_source_dict(self) -> dict[str, Any]:
        """Schema-compliant source location dict."""
        return {
            "path": self.source_path,
            "anchor": self.anchor or "",
            "heading": self.heading or "",
            "line_start": max(1, self.line_start),
            "line_end": max(1, self.line_end),
        }


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

@dataclass
class TaxonomyEntry:
    subsystem: Optional[str] = None
    maintenance_category: Optional[str] = None
    symptom_terms: list[str] = field(default_factory=list)
    component_terms: list[str] = field(default_factory=list)
    tool_terms: list[str] = field(default_factory=list)
    candidate_terms: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Schema-compliant taxonomy dict."""
        controlled_core: dict[str, Any] = {
            "subsystems": [self.subsystem] if self.subsystem else [],
            "maintenance_categories": [self.maintenance_category] if self.maintenance_category else [],
            "safety_types": [],
        }
        return {
            "controlled_core": controlled_core,
            "candidate_terms": self.candidate_terms,
            "quarantine_terms": [],
            "extracted_requirements": {
                "tools": self.tool_terms,
                "materials": [],
            },
        }


# ---------------------------------------------------------------------------
# Top-level ContentUnit
# ---------------------------------------------------------------------------

@dataclass
class ContentUnit:
    schema_version: str
    content_id: str
    manual_id: str
    manual_role: str  # operator | maintenance | parts | engine | other
    mode: ModeMetadata
    source: Provenance
    unit_type: str
    title: str
    text_markdown: str
    text_plain: str
    provenance: Provenance
    taxonomy: TaxonomyEntry

    chapter: Optional[str] = None
    section: Optional[str] = None
    subsection: Optional[str] = None

    warnings: list[SafetyBlock] = field(default_factory=list)
    cautions: list[SafetyBlock] = field(default_factory=list)
    notes: list[SafetyBlock] = field(default_factory=list)

    procedure: Optional[ProcedureBlock] = None
    troubleshooting: Optional[TroubleshootingBlock] = None
    diagnostic_flow: Optional[DiagnosticFlowBlock] = None

    cross_manual_refs: list[CrossRef] = field(default_factory=list)
    image_refs: list[str] = field(default_factory=list)
    follow_on_links: list[str] = field(default_factory=list)

    parent_flow_id: Optional[str] = None
    node_type: Optional[str] = None  # for diagnostic_flow_node units

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "content_id": self.content_id,
            "manual_id": self.manual_id,
            "manual_role": self.manual_role,
            "mode": self.mode.to_dict(),
            "source": self.source.to_source_dict(),
            "unit_type": self.unit_type,
            "title": self.title,
            "text_markdown": self.text_markdown,
            "text_plain": self.text_plain,
            "provenance": self.provenance.to_dict(),
            "taxonomy": self.taxonomy.to_dict(),
        }
        # Optional scalar fields
        for f_name in ("chapter", "section", "subsection"):
            val = getattr(self, f_name)
            if val is not None:
                d[f_name] = val

        # Safety blocks — map warnings/cautions/notes → safety_blocks
        safety_blocks = []
        for block in self.warnings:
            safety_blocks.append({"type": "warning", "text": block.text})
        for block in self.cautions:
            safety_blocks.append({"type": "caution", "text": block.text})
        for block in self.notes:
            safety_blocks.append({"type": "note", "text": block.text})
        if safety_blocks:
            d["safety_blocks"] = safety_blocks

        # Procedure — flatten to schema top-level fields
        if self.procedure:
            if self.procedure.initial_setup:
                d["initial_setup"] = {
                    "tools": [],
                    "special_tools": [],
                    "materials_parts": self.procedure.initial_setup,
                    "personnel_required": [],
                    "manual_references": [],
                    "equipment_condition": [],
                    "general_safety_instructions": [],
                }
            if self.procedure.steps:
                d["procedure_steps"] = [
                    {
                        "sequence": step.step_number,
                        "text": step.text,
                        "phase": "execution",
                    }
                    for step in self.procedure.steps
                ]
            if self.procedure.follow_on_tasks:
                d["follow_on_tasks"] = [
                    {"text": t}
                    for t in self.procedure.follow_on_tasks
                ]

        # Troubleshooting — map to schema troubleshooting block
        if self.troubleshooting:
            # Serialize branches into decision_order (condition labels) and actions (target descriptions)
            decision_order = [b.condition for b in self.troubleshooting.branches]
            actions = [
                b.target_text or (f"Go to {b.target_anchor}" if b.target_anchor else b.condition)
                for b in self.troubleshooting.branches
            ]
            # Distinguish symptom from question: symptom is the observable problem description,
            # question is the check prompt. If both come from the heading, deduplicate.
            symptom = self.troubleshooting.symptom or ""
            question = self.troubleshooting.question or ""
            if symptom == question:
                # Heading is both the symptom and the check question — acceptable; leave as-is
                pass
            d["troubleshooting"] = {
                "symptom": symptom,
                "question": question,
                "decision_order": decision_order,
                "actions": actions,
                "escalation": None,
            }

        # Diagnostic graph — map flow container to schema diagnostic_graph
        if self.diagnostic_flow:
            df = self.diagnostic_flow
            d["diagnostic_graph"] = {
                "flow_container": {
                    "flow_id": df.flow_id,
                    "entry_node_ids": df.entry_node_ids,
                    "retrieval_identity": df.flow_id,
                },
                "nodes": [
                    {"node_id": n, "node_type": "check", "text": df.node_texts.get(n, "")}
                    for n in df.node_ids
                ],
                "edges": [
                    {
                        "edge_id": f"{e.from_node}__to__{e.to_node}_{eidx}",
                        "from_node_id": e.from_node,
                        "to_node_id": e.to_node,
                        "condition_label": e.condition,
                    }
                    for eidx, e in enumerate(df.edges)
                ],
                "support_panels": [],
                "render_views": {
                    "retrieval_view": "graph_nodes",
                    "technician_view": "guided_path",
                    "default_entry_node_id": df.entry_node_ids[0] if df.entry_node_ids else "",
                },
            }

        # Relations — map cross_manual_refs and follow_on_links to relations array
        relations = []
        for ref in self.cross_manual_refs:
            relations.append({
                "type": "cross_manual_reference",
                "label": ref.source_string,
                "target": ref.target_manual or ref.target_anchor or ref.target_section or "",
            })
        for link in self.follow_on_links:
            relations.append({"type": "follow_on_reference", "label": link, "target": link})
        if relations:
            d["relations"] = relations

        # Image refs — map to schema imageRef objects
        if self.image_refs:
            d["image_refs"] = [{"path": p, "caption": None} for p in self.image_refs]

        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ContentUnit":
        mode = ModeMetadata(**d["mode"])
        prov = Provenance(**d["provenance"])
        src = Provenance(**d["source"]) if "source" in d else prov
        tax = TaxonomyEntry(**d["taxonomy"])

        warnings = [SafetyBlock(**b) for b in d.get("warnings", [])]
        cautions = [SafetyBlock(**b) for b in d.get("cautions", [])]
        notes = [SafetyBlock(**b) for b in d.get("notes", [])]

        proc = None
        if "procedure" in d:
            steps = [
                ProcedureStep(
                    step_number=s["step_number"],
                    text=s["text"],
                    sub_steps=s.get("sub_steps", []),
                )
                for s in d["procedure"].get("steps", [])
            ]
            proc = ProcedureBlock(
                initial_setup=d["procedure"].get("initial_setup", []),
                steps=steps,
                follow_on_tasks=d["procedure"].get("follow_on_tasks", []),
            )

        trouble = None
        if "troubleshooting" in d:
            branches = [TroubleshootingBranch(**b) for b in d["troubleshooting"].get("branches", [])]
            trouble = TroubleshootingBlock(
                symptom=d["troubleshooting"].get("symptom"),
                question=d["troubleshooting"].get("question"),
                branches=branches,
            )

        df = None
        if "diagnostic_flow" in d:
            edges = [DiagnosticEdge(**e) for e in d["diagnostic_flow"].get("edges", [])]
            df = DiagnosticFlowBlock(
                flow_id=d["diagnostic_flow"]["flow_id"],
                entry_node_ids=d["diagnostic_flow"].get("entry_node_ids", []),
                node_ids=d["diagnostic_flow"].get("node_ids", []),
                edges=edges,
                support_panel_ids=d["diagnostic_flow"].get("support_panel_ids", []),
            )

        cross_refs = [CrossRef(**r) for r in d.get("cross_manual_refs", [])]

        return cls(
            schema_version=d["schema_version"],
            content_id=d["content_id"],
            manual_id=d["manual_id"],
            manual_role=d["manual_role"],
            mode=mode,
            source=src,
            unit_type=d["unit_type"],
            title=d["title"],
            text_markdown=d["text_markdown"],
            text_plain=d["text_plain"],
            provenance=prov,
            taxonomy=tax,
            chapter=d.get("chapter"),
            section=d.get("section"),
            subsection=d.get("subsection"),
            warnings=warnings,
            cautions=cautions,
            notes=notes,
            procedure=proc,
            troubleshooting=trouble,
            diagnostic_flow=df,
            cross_manual_refs=cross_refs,
            image_refs=d.get("image_refs", []),
            follow_on_links=d.get("follow_on_links", []),
            parent_flow_id=d.get("parent_flow_id"),
            node_type=d.get("node_type"),
        )
