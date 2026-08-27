"""
ingestion/run_ingestion.py

CLI entrypoint for the full ingestion pipeline.

Usage:
    python -m ingestion.run_ingestion \\
        --corpus-root . \\
        --output-dir output/ingestion \\
        [--schema-path schemas/rag-diagnostic/content-unit.schema.json] \\
        [--taxonomy-path schemas/rag-diagnostic/taxonomy.json] \\
        [--fail-on-error]

Produces:
    output/ingestion/
        content-units.jsonl
        keyword-index.json
        cross-reference-map.json
        troubleshooting-graph.json
        qa-report.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ingestion.chunker import build_content_units
from ingestion.enrichment import (
    build_cross_reference_map,
    build_keyword_index,
    build_troubleshooting_graph,
)
from ingestion.loader import MVP_MANUAL_IDS, discover_sources
from ingestion.models import ContentUnit
from ingestion.parser import parse_chapter
from ingestion.qa import (
    run_all_checks,
    write_qa_report,
    SEVERITY_ERROR,
)
from ingestion.validate import validate_unit


def _build_expected_chapters(sources) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for rec in sources:
        result.setdefault(rec.manual_id, []).append(rec.chapter_name)
    return result


def run(
    corpus_root: Path,
    output_dir: Path,
    schema_path: Path,
    taxonomy_path: Path,
    fail_on_error: bool = False,
) -> int:
    t0 = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== HMMWV RAG Ingestion Pipeline ===")
    print(f"Corpus root : {corpus_root}")
    print(f"Output dir  : {output_dir}")
    print()

    # 1. Discover sources
    print("Step 1/7  Discovering source files...")
    sources = discover_sources(corpus_root)
    print(f"          Found {len(sources)} chapter files across {len(MVP_MANUAL_IDS)} manuals.")

    # 2. Parse + chunk
    print("Step 2/7  Parsing and chunking...")
    all_units: list[ContentUnit] = []
    for rec in sources:
        t1 = time.perf_counter()
        raw_blocks = parse_chapter(rec.chapter_path, rec.manual_id, rec.manual_role)
        units = build_content_units(
            raw_blocks,
            manual_id=rec.manual_id,
            manual_role=rec.manual_role,
            source_path=str(rec.chapter_path),
            chapter_name=rec.chapter_name,
        )
        all_units.extend(units)
        elapsed = time.perf_counter() - t1
        print(f"          {rec.manual_id}/{rec.chapter_name}: "
              f"{len(raw_blocks)} blocks → {len(units)} units  ({elapsed:.1f}s)")

    print(f"          Total units: {len(all_units)}")

    # 3. Schema validation
    print("Step 3/7  Validating schema...")
    validation_results: list[tuple[str, bool, list[str]]] = []
    invalid_count = 0
    for unit in all_units:
        d = unit.to_dict()
        is_valid, errors = validate_unit(d, schema_path)
        validation_results.append((unit.content_id, is_valid, errors))
        if not is_valid:
            invalid_count += 1
    print(f"          {len(all_units) - invalid_count}/{len(all_units)} units pass schema validation.")

    # 4. Enrichment
    print("Step 4/7  Building keyword index...")
    keyword_index = build_keyword_index(all_units, taxonomy_path)
    print(f"          {len(keyword_index)} indexed terms.")

    print("Step 5/7  Building cross-reference map...")
    xref_map = build_cross_reference_map(all_units)
    print(f"          {sum(len(v) for v in xref_map.values())} cross-references.")

    print("Step 6/7  Building troubleshooting graph...")
    trouble_graph = build_troubleshooting_graph(all_units)
    n_flows = len(trouble_graph.get("flows", {}))
    n_standalone = len(trouble_graph.get("standalone_troubleshooting", []))
    print(f"          {n_flows} diagnostic flows, {n_standalone} standalone troubleshooting entries.")

    # 5. QA checks
    print("Step 7/7  Running QA checks...")
    expected_chapters = _build_expected_chapters(sources)
    issues = run_all_checks(
        units=all_units,
        expected_manuals=MVP_MANUAL_IDS,
        expected_chapters=expected_chapters,
        validation_results=validation_results,
    )
    errors = [i for i in issues if i.severity == SEVERITY_ERROR]
    warnings = [i for i in issues if i.severity != SEVERITY_ERROR]
    print(f"          {len(errors)} errors, {len(warnings)} warnings.")

    # 6. Write outputs
    units_path = output_dir / "content-units.jsonl"
    with units_path.open("w", encoding="utf-8") as f:
        for unit in all_units:
            f.write(json.dumps(unit.to_dict(), ensure_ascii=False) + "\n")
    print(f"\nWrote {len(all_units)} content units → {units_path}")

    kw_path = output_dir / "keyword-index.json"
    kw_path.write_text(json.dumps(keyword_index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote keyword index     → {kw_path}")

    xref_path = output_dir / "cross-reference-map.json"
    xref_path.write_text(json.dumps(xref_map, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote cross-ref map     → {xref_path}")

    graph_path = output_dir / "troubleshooting-graph.json"
    graph_path.write_text(json.dumps(trouble_graph, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote troubleshooting graph → {graph_path}")

    qa_path = output_dir / "qa-report.md"
    write_qa_report(issues, all_units, qa_path)
    print(f"Wrote QA report         → {qa_path}")

    elapsed_total = time.perf_counter() - t0
    print(f"\nIngestion complete in {elapsed_total:.1f}s.")

    if fail_on_error and errors:
        print(f"\n[FAIL] {len(errors)} QA errors — see {qa_path}", file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="HMMWV RAG Ingestion Pipeline")
    parser.add_argument("--corpus-root", type=Path, default=Path("."),
                        help="Root of the hmmwv-manuals repository.")
    parser.add_argument("--output-dir", type=Path, default=Path("output/ingestion"),
                        help="Directory to write output artifacts.")
    parser.add_argument("--schema-path", type=Path,
                        default=Path("schemas/rag-diagnostic/content-unit.schema.json"),
                        help="Path to the content-unit JSON schema.")
    parser.add_argument("--taxonomy-path", type=Path,
                        default=Path("schemas/rag-diagnostic/taxonomy.json"),
                        help="Path to the taxonomy JSON.")
    parser.add_argument("--fail-on-error", action="store_true",
                        help="Exit non-zero if any QA error is found.")
    args = parser.parse_args()

    sys.exit(run(
        corpus_root=args.corpus_root,
        output_dir=args.output_dir,
        schema_path=args.schema_path,
        taxonomy_path=args.taxonomy_path,
        fail_on_error=args.fail_on_error,
    ))


if __name__ == "__main__":
    main()
