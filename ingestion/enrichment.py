"""
ingestion/enrichment.py

Builds enrichment artifacts from a list of ContentUnit objects:
  1. Keyword index: term → [content_id, ...]
  2. Cross-reference map: source_content_id → [CrossRef, ...]
  3. Troubleshooting graph: adjacency dict of diagnostic flows
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ingestion.models import ContentUnit


# ---------------------------------------------------------------------------
# Keyword index
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+(?:[-/][a-zA-Z0-9]+)*", text.lower())


def build_keyword_index(
    units: list[ContentUnit],
    taxonomy_path: Path,
) -> dict[str, list[str]]:
    """
    Build an inverted index: term → sorted list of content_ids.

    Terms are drawn from:
      - Taxonomy controlled terms and candidate terms
      - Unit taxonomy fields (symptom_terms, component_terms, tool_terms)
    """
    # Load taxonomy to get approved term lists
    controlled_terms: set[str] = set()
    if taxonomy_path.exists():
        tax_data = json.loads(taxonomy_path.read_text(encoding="utf-8"))
        for section in ("symptom_terms", "component_terms", "tool_terms"):
            terms = tax_data.get(section, [])
            if isinstance(terms, list):
                for t in terms:
                    if isinstance(t, str):
                        controlled_terms.add(t.lower())
                    elif isinstance(t, dict):
                        for v in t.values():
                            if isinstance(v, str):
                                controlled_terms.add(v.lower())
        # Also ingest subsystem values
        for sub in tax_data.get("subsystems", []):
            if isinstance(sub, str):
                controlled_terms.add(sub.lower())

    index: dict[str, set[str]] = defaultdict(set)

    for unit in units:
        cid = unit.content_id

        # From taxonomy fields
        for term in unit.taxonomy.symptom_terms + unit.taxonomy.component_terms + unit.taxonomy.tool_terms:
            index[term.lower()].add(cid)

        # From text content — match controlled terms
        combined_text = (unit.title + " " + unit.text_plain).lower()
        for term in controlled_terms:
            if term in combined_text:
                index[term].add(cid)

        # From candidate_terms
        for ct in unit.taxonomy.candidate_terms:
            term = ct.get("term", "").lower()
            if term:
                index[term].add(cid)

    return {term: sorted(ids) for term, ids in sorted(index.items())}


# ---------------------------------------------------------------------------
# Cross-reference map
# ---------------------------------------------------------------------------

def build_cross_reference_map(
    units: list[ContentUnit],
) -> dict[str, list[dict[str, Any]]]:
    """
    Build bidirectional cross-reference map.
    Returns: {source_content_id: [{"target_manual": ..., "target_anchor": ..., ...}]}
    """
    forward: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for unit in units:
        for ref in unit.cross_manual_refs:
            forward[unit.content_id].append({
                "source_string": ref.source_string,
                "target_manual": ref.target_manual,
                "target_anchor": ref.target_anchor,
                "target_section": ref.target_section,
            })

    return dict(forward)


# ---------------------------------------------------------------------------
# Troubleshooting graph
# ---------------------------------------------------------------------------

def build_troubleshooting_graph(
    units: list[ContentUnit],
) -> dict[str, Any]:
    """
    Build a JSON-serializable adjacency representation of diagnostic flows.

    Output format:
    {
      "flows": {
        "<flow_id>": {
          "title": ...,
          "entry_nodes": [...],
          "nodes": {
            "<node_id>": {
              "title": ...,
              "node_type": ...,
              "unit_type": ...,
              "source_path": ...,
              "anchor": ...,
            }
          },
          "edges": [
            {"from": ..., "to": ..., "condition": ...}
          ]
        }
      },
      "standalone_troubleshooting": [content_id, ...]
    }
    """
    # Index nodes by parent_flow_id
    flow_nodes: dict[str, list[ContentUnit]] = defaultdict(list)
    flow_containers: dict[str, ContentUnit] = {}
    standalone: list[str] = []

    for unit in units:
        if unit.unit_type == "diagnostic_flow":
            flow_containers[unit.diagnostic_flow.flow_id] = unit
        elif unit.unit_type == "diagnostic_flow_node" and unit.parent_flow_id:
            flow_nodes[unit.parent_flow_id].append(unit)
        elif unit.unit_type == "troubleshooting_entry":
            standalone.append(unit.content_id)

    flows: dict[str, Any] = {}
    for flow_id, container in flow_containers.items():
        df = container.diagnostic_flow
        nodes: dict[str, Any] = {}
        for node_unit in flow_nodes.get(flow_id, []):
            nodes[node_unit.content_id] = {
                "title": node_unit.title,
                "node_type": node_unit.node_type or "check",
                "unit_type": node_unit.unit_type,
                "source_path": node_unit.provenance.source_path,
                "anchor": node_unit.provenance.anchor,
            }
        flows[flow_id] = {
            "title": container.title,
            "manual_id": container.manual_id,
            "entry_nodes": df.entry_node_ids,
            "nodes": nodes,
            "edges": [{"from": e.from_node, "to": e.to_node, "condition": e.condition}
                      for e in df.edges],
        }

    return {
        "flows": flows,
        "standalone_troubleshooting": standalone,
    }
