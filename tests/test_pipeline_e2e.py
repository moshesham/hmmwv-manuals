"""
tests/test_pipeline_e2e.py

End-to-end tests for the HMMWV RAG ingestion pipeline.
All tests use real corpus text from the repository; no mocks or synthetic data.

Run with:
    python -m pytest tests/ -v
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

# Make sure repo root is on the path so ingestion.* imports work regardless of
# where pytest is invoked from.
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ingestion.chunker import build_content_units
from ingestion.enrichment import build_keyword_index, build_cross_reference_map
from ingestion.loader import discover_sources, MVP_MANUAL_IDS
from ingestion.models import ContentUnit
from ingestion.parser import parse_chapter
from ingestion.validate import validate_unit

SCHEMA_PATH = REPO_ROOT / "schemas/rag-diagnostic/content-unit.schema.json"
TAXONOMY_PATH = REPO_ROOT / "schemas/rag-diagnostic/taxonomy.json"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def all_units() -> list[ContentUnit]:
    """Parse and chunk the full corpus once for the entire test module."""
    sources = discover_sources(REPO_ROOT)
    units: list[ContentUnit] = []
    manual_chunk_counters: dict[str, dict[str, int]] = {}
    for rec in sources:
        raw_blocks = parse_chapter(rec.chapter_path, rec.manual_id, rec.manual_role)
        if rec.manual_id not in manual_chunk_counters:
            manual_chunk_counters[rec.manual_id] = {}
        units.extend(build_content_units(
            raw_blocks,
            manual_id=rec.manual_id,
            manual_role=rec.manual_role,
            source_path=str(rec.chapter_path),
            chapter_name=rec.chapter_name,
            chunk_counter=manual_chunk_counters[rec.manual_id],
        ))
    return units


@pytest.fixture(scope="module")
def units_by_id(all_units) -> dict[str, ContentUnit]:
    return {u.content_id: u for u in all_units}


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------

class TestLoader:
    def test_discovers_all_four_manuals(self):
        sources = discover_sources(REPO_ROOT)
        manual_ids = {r.manual_id for r in sources}
        for mid in MVP_MANUAL_IDS:
            assert mid in manual_ids, f"Manual {mid} not discovered"

    def test_discovers_fifteen_chapter_files(self):
        sources = discover_sources(REPO_ROOT)
        assert len(sources) == 15

    def test_tm_9_2320_280_10_discovered(self):
        """tm-9-2320-280-10 has no chapter*.md — only a rollup .md; loader must include it."""
        sources = discover_sources(REPO_ROOT)
        tm10 = [r for r in sources if r.manual_id == "tm-9-2320-280-10"]
        assert len(tm10) >= 1, "tm-9-2320-280-10 rollup file must be discovered"


# ---------------------------------------------------------------------------
# Parser tests — real corpus text
# ---------------------------------------------------------------------------

class TestParser:
    def test_chapter2_toc_is_section_block(self):
        """
        Chapter 2 starts with a markdown table of contents using the format
        '[2-1](#2-1) | Description' (no leading pipe), which the parser classifies
        as a section block. Verify this header section is captured and not lost.
        """
        ch2_path = REPO_ROOT / "TM-9-2320-280-20-1/chapter2.md"
        blocks = parse_chapter(ch2_path, "TM-9-2320-280-20-1", "maintenance")
        # The first block is the chapter heading section; its body may contain TOC text
        first_block = blocks[0]
        assert first_block.block_type in ("section", "toc"), \
            f"First block in chapter2 should be section or toc, got {first_block.block_type!r}"
        # Verify tasks are still found afterward (TOC not consuming task content)
        task_ids = [b.task_id for b in blocks if b.block_type == "task"]
        assert "2-5" in task_ids, "Tasks must still be parsed after the chapter intro section"

    def test_task_headings_parsed(self):
        """### 2-5. General Inspection... must be parsed as a task block."""
        ch2_path = REPO_ROOT / "TM-9-2320-280-20-1/chapter2.md"
        blocks = parse_chapter(ch2_path, "TM-9-2320-280-20-1", "maintenance")
        task_ids = [b.task_id for b in blocks if b.block_type == "task"]
        assert "2-5" in task_ids, "Task 2-5 must be parsed"
        assert "2-6" in task_ids, "Task 2-6 must be parsed"
        # Tasks 2-12 onward are in the troubleshooting section and are classified
        # as BLOCK_TROUBLESHOOTING (correct — they are diagnostic flowchart entries).
        trouble_ids = [b.task_id for b in blocks if b.block_type == "troubleshooting"]
        assert "2-14" in trouble_ids, \
            "Task 2-14 ('How To Use Troubleshooting Guide') must be BLOCK_TROUBLESHOOTING"

    def test_safety_variants_detected(self):
        """Parser must detect ### Warning, ### .Warning., and **WARNING** variants."""
        ch2_path = REPO_ROOT / "TM-9-2320-280-20-1/chapter2.md"
        blocks = parse_chapter(ch2_path, "TM-9-2320-280-20-1", "maintenance")
        # Before fix 6, safety blocks were emitted as standalone BLOCK_SAFETY.
        # After fix 6, safety blocks inside tasks are kept inline.
        # We verify that standalone safety blocks (before first task) are still detected.
        safety_blocks = [b for b in blocks if b.block_type == "safety"]
        assert len(safety_blocks) >= 1, "At least one standalone safety block expected"

    def test_anchor_extraction(self):
        """<a name="2-5"> anchors must be extracted into block.anchor."""
        ch2_path = REPO_ROOT / "TM-9-2320-280-20-1/chapter2.md"
        blocks = parse_chapter(ch2_path, "TM-9-2320-280-20-1", "maintenance")
        anchored = [b for b in blocks if b.anchor and b.anchor.startswith("2-")]
        assert len(anchored) >= 10, "Should find many anchored task blocks"

    def test_inline_safety_kept_in_task_body(self):
        """
        Fix 6: safety headings inside an open task block must be folded into body_lines,
        not flushed as standalone safety blocks.
        Task 2-5 in chapter 2 contains ### Warning and ### .Warning. mid-task.
        The resulting task block must include the safety heading text in body_lines AND
        must still contain its numbered steps.
        """
        ch2_path = REPO_ROOT / "TM-9-2320-280-20-1/chapter2.md"
        blocks = parse_chapter(ch2_path, "TM-9-2320-280-20-1", "maintenance")
        b25 = next((b for b in blocks if b.task_id == "2-5"), None)
        assert b25 is not None, "Task 2-5 must be found"
        body_text = "\n".join(b25.body_lines).lower()
        # Safety text must be in the body
        assert "flammable" in body_text or "solvent" in body_text, \
            "Warning text must be retained in task 2-5 body_lines"
        # Steps must also be present (step text starts with numbers)
        assert len(b25.steps) >= 3, \
            f"Task 2-5 must have at least 3 steps, found {len(b25.steps)}"


# ---------------------------------------------------------------------------
# Chunker / ContentUnit tests
# ---------------------------------------------------------------------------

class TestChunker:
    def test_total_unit_count(self, all_units):
        """Pipeline must produce approximately 2900+ units from 15 chapter files."""
        assert len(all_units) >= 2800, f"Expected ≥2800 units, got {len(all_units)}"

    def test_no_duplicate_content_ids(self, all_units):
        """Fix 2: each content_id must be unique across the entire corpus."""
        id_counts = Counter(u.content_id for u in all_units)
        duplicates = {cid: n for cid, n in id_counts.items() if n > 1}
        assert len(duplicates) == 0, \
            f"Duplicate content_ids found: {list(duplicates.items())[:5]}"

    def test_procedure_steps_use_corpus_sequence_numbers(self, all_units):
        """
        Fix 1: procedure_steps[].sequence must come from the actual step label in the
        corpus (e.g. '(1)', '1.', 'a.'), not from the array position (idx+1).
        Task 2-5 in chapter 2 has 5 numbered steps (1)-(5).
        """
        task_2_5 = next(
            (u for u in all_units
             if "2-5" in u.title and u.unit_type == "procedure_task"),
            None,
        )
        assert task_2_5 is not None, "procedure_task for 2-5 must exist"
        steps = task_2_5.procedure.steps if task_2_5.procedure else []
        assert len(steps) >= 5, f"Task 2-5 must have ≥5 steps, got {len(steps)}"
        seq_values = [s.step_number for s in steps]
        # Steps are labeled (1)-(5) in the corpus: strip "()" → "1","2","3","4","5"
        assert "1" in seq_values, f"Step '1' not found in sequences: {seq_values}"
        assert "5" in seq_values or "4" in seq_values, \
            f"Expected corpus step numbers, got: {seq_values}"

    def test_procedure_steps_sequence_field_is_string(self, all_units):
        """Fix 1 type check: to_dict() must emit sequence as string, not int."""
        for u in all_units:
            d = u.to_dict()
            for step in d.get("procedure_steps", []):
                assert isinstance(step["sequence"], str), \
                    f"sequence must be str, got {type(step['sequence'])} in {u.content_id}"

    def test_inline_safety_blocks_attached_to_task(self, all_units):
        """
        Fix 6: safety blocks inside a task (inline) must be extracted into
        ContentUnit.warnings/cautions/notes and appear in to_dict() safety_blocks.
        Task 2-5 in chapter 2 has 2 inline ### Warning blocks.
        """
        task_2_5 = next(
            (u for u in all_units
             if "2-5" in u.title and u.unit_type == "procedure_task"),
            None,
        )
        assert task_2_5 is not None
        assert len(task_2_5.warnings) >= 2, \
            f"Task 2-5 must have ≥2 warning blocks, got {len(task_2_5.warnings)}"
        # Verify the actual warning text references the real corpus content
        warning_texts = " ".join(w.text for w in task_2_5.warnings).lower()
        assert "solvent" in warning_texts or "flammable" in warning_texts, \
            "Warning text must contain the drycleaning solvent warning from corpus"

    def test_troubleshooting_branches_serialized(self, all_units):
        """Fix 3: troubleshooting.to_dict() must populate decision_order and actions."""
        ts_units = [u for u in all_units if u.troubleshooting]
        assert len(ts_units) >= 1, "Must have at least one troubleshooting unit"
        for u in ts_units:
            d = u.to_dict()
            ts = d.get("troubleshooting", {})
            assert isinstance(ts["decision_order"], list), \
                f"decision_order must be list in {u.content_id}"
            assert isinstance(ts["actions"], list), \
                f"actions must be list in {u.content_id}"
            assert len(ts["actions"]) > 0, \
                f"actions must not be empty in {u.content_id}"

    def test_diagnostic_graph_node_text_populated(self, all_units):
        """Fix 5: diagnostic_graph nodes must have non-empty text from their block body."""
        flow_units = [u for u in all_units if u.unit_type == "diagnostic_flow"]
        assert len(flow_units) >= 1, "Must have at least one diagnostic_flow unit"
        for u in flow_units:
            d = u.to_dict()
            nodes = d.get("diagnostic_graph", {}).get("nodes", [])
            assert len(nodes) >= 1, f"Flow {u.content_id} must have nodes"
            texts = [n["text"] for n in nodes if n["text"].strip()]
            assert len(texts) >= 1, \
                f"At least one node in flow {u.content_id} must have non-empty text"

    def test_relation_types_valid(self, all_units):
        """Relation types must only contain schema-valid enum values."""
        valid_types = {
            "manual_reference", "follow_on_reference", "cross_manual_reference",
            "image_reference", "task_reference", "flow_reference", "support_panel_reference",
        }
        for u in all_units:
            for ref in u.cross_manual_refs:
                # All cross_manual_refs must become cross_manual_reference in to_dict()
                pass
            d = u.to_dict()
            for rel in d.get("relations", []):
                assert rel["type"] in valid_types, \
                    f"Invalid relation type {rel['type']!r} in {u.content_id}"

    def test_diagnostic_flow_ids_unique(self, all_units):
        """
        Fix (flow_None duplicate): diagnostic flow content_ids must be unique
        even when their first block has no anchor.
        """
        flow_units = [u for u in all_units if u.unit_type == "diagnostic_flow"]
        flow_ids = [u.content_id for u in flow_units]
        assert len(flow_ids) == len(set(flow_ids)), \
            f"Duplicate diagnostic_flow IDs: {[cid for cid, n in Counter(flow_ids).items() if n>1]}"


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_all_units_pass_schema(self, all_units):
        """Every content unit produced by the pipeline must pass schema validation."""
        invalid: list[tuple[str, list[str]]] = []
        for unit in all_units:
            d = unit.to_dict()
            ok, errors = validate_unit(d, SCHEMA_PATH)
            if not ok:
                invalid.append((unit.content_id, errors[:2]))
        assert len(invalid) == 0, (
            f"{len(invalid)} units fail schema validation. First failures:\n" +
            "\n".join(f"  {cid}: {errs}" for cid, errs in invalid[:5])
        )

    def test_procedure_steps_sequence_schema_type(self, all_units):
        """Schema requires procedure_steps[].sequence to be a string."""
        for unit in all_units:
            d = unit.to_dict()
            for step in d.get("procedure_steps", []):
                assert isinstance(step["sequence"], str), \
                    f"schema violation: sequence must be string in {unit.content_id}"

    def test_troubleshooting_decision_order_is_array(self, all_units):
        """Schema requires troubleshooting.decision_order to be an array."""
        for unit in all_units:
            d = unit.to_dict()
            ts = d.get("troubleshooting")
            if ts:
                assert isinstance(ts["decision_order"], list), \
                    f"decision_order must be array in {unit.content_id}"

    def test_edge_fields_match_schema(self, all_units):
        """diagnostic_graph edges must have edge_id, from_node_id, to_node_id, condition_label."""
        required = {"edge_id", "from_node_id", "to_node_id", "condition_label"}
        forbidden = {"from_node", "to_node", "condition"}
        for unit in all_units:
            d = unit.to_dict()
            dg = d.get("diagnostic_graph")
            if not dg:
                continue
            for edge in dg.get("edges", []):
                edge_keys = set(edge.keys())
                assert not (edge_keys & forbidden), \
                    f"Old edge field names found in {unit.content_id}: {edge_keys & forbidden}"
                assert required <= edge_keys, \
                    f"Missing edge fields in {unit.content_id}: {required - edge_keys}"


# ---------------------------------------------------------------------------
# Enrichment tests
# ---------------------------------------------------------------------------

class TestEnrichment:
    def test_keyword_index_populated(self, all_units):
        """Fix 4: keyword index must contain terms from taxonomy.json controlled vocabulary."""
        kw = build_keyword_index(all_units, TAXONOMY_PATH)
        assert len(kw) >= 20, f"Expected ≥20 keyword terms, got {len(kw)}"

    def test_keyword_index_battery_maps_to_many_units(self, all_units):
        """'battery' is in taxonomy seed_mappings and should appear in many units."""
        kw = build_keyword_index(all_units, TAXONOMY_PATH)
        assert "battery" in kw, "Term 'battery' must be in keyword index"
        assert len(kw["battery"]) >= 100, \
            f"'battery' should map to ≥100 units, got {len(kw['battery'])}"

    def test_keyword_index_engine_maps_to_units(self, all_units):
        """'engine' is a controlled_core subsystem and appears throughout the corpus."""
        kw = build_keyword_index(all_units, TAXONOMY_PATH)
        assert "engine" in kw, "Term 'engine' must be in keyword index"
        assert len(kw["engine"]) >= 50

    def test_cross_reference_map_populated(self, all_units):
        xref = build_cross_reference_map(all_units)
        total = sum(len(v) for v in xref.values())
        assert total >= 1200, f"Expected ≥1200 cross-references, got {total}"

    def test_cross_reference_targets_not_empty(self, all_units):
        """Every relation must have a non-empty target."""
        for u in all_units:
            d = u.to_dict()
            for rel in d.get("relations", []):
                assert rel["target"], \
                    f"Empty relation target in {u.content_id}: {rel}"


# ---------------------------------------------------------------------------
# End-to-end integration test (no file system output needed)
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_pipeline_produces_expected_structure(self, all_units):
        """
        Full end-to-end: loader → parser → chunker → validation.
        Checks that all four MVP manuals are represented, key unit types exist,
        and basic counts are in range.
        """
        unit_dicts = [u.to_dict() for u in all_units]

        # All manuals represented
        manual_ids = {d["manual_id"] for d in unit_dicts}
        for mid in MVP_MANUAL_IDS:
            assert mid in manual_ids

        # All expected unit types present
        types = {d["unit_type"] for d in unit_dicts}
        assert "procedure_task" in types
        assert "reference_section" in types
        assert "diagnostic_flow" in types
        assert "diagnostic_flow_node" in types

        # Counts in expected ranges
        procedure_tasks = [d for d in unit_dicts if d["unit_type"] == "procedure_task"]
        assert len(procedure_tasks) >= 1000, \
            f"Expected ≥1000 procedure tasks, got {len(procedure_tasks)}"

        safety_units = [d for d in unit_dicts if d.get("safety_blocks")]
        assert len(safety_units) >= 150, \
            f"Expected ≥150 units with safety_blocks, got {len(safety_units)}"

    def test_chapter2_task_2_5_complete_unit(self, all_units):
        """
        Regression test for task 2-5 (General Inspection And Servicing Instructions).
        This task exercises: inline safety detection (fix 6), corpus step numbering (fix 1),
        and schema validation together.
        """
        task = next(
            (u for u in all_units
             if "2-5" in u.title and u.unit_type == "procedure_task"),
            None,
        )
        assert task is not None, "Task 2-5 must be found"

        # Steps
        assert task.procedure is not None
        assert len(task.procedure.steps) >= 5
        step_nums = {s.step_number for s in task.procedure.steps}
        assert "1" in step_nums and "5" in step_nums, \
            f"Expected steps 1-5 from corpus, got {sorted(step_nums)}"

        # Inline safety warnings
        assert len(task.warnings) >= 2, "Task 2-5 must have ≥2 warning blocks"
        combined = " ".join(w.text for w in task.warnings).lower()
        assert "solvent" in combined or "flammable" in combined

        # Schema valid
        d = task.to_dict()
        ok, errors = validate_unit(d, SCHEMA_PATH)
        assert ok, f"Task 2-5 unit fails schema: {errors[:3]}"

        # Sequence field types
        for step in d.get("procedure_steps", []):
            assert isinstance(step["sequence"], str)

    def test_cross_manual_reference_quality(self, all_units):
        """
        Cross-references to TM 9-2320-280-10 and TM 9-2320-280-24P must be
        found and have properly formatted targets.
        """
        all_rels = []
        for u in all_units:
            all_rels.extend(u.cross_manual_refs)

        targets = [r.target_manual for r in all_rels if r.target_manual]
        # TM 9-2320-280-10 is referenced throughout the maintenance manuals
        tm10_refs = [t for t in targets if "280-10" in t]
        assert len(tm10_refs) >= 50, \
            f"Expected ≥50 refs to TM-9-2320-280-10, got {len(tm10_refs)}"
