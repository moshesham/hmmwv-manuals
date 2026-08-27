"""
vector_index/run_indexer.py

CLI entrypoint for building/updating the vector index.

Usage:
    python -m vector_index.run_indexer \\
        --content-units output/ingestion/content-units.jsonl \\
        --index-dir output/vector_index \\
        [--model sentence-transformers/all-MiniLM-L6-v2] \\
        [--device cpu] \\
        [--incremental] \\
        [--force-rebuild]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vector_index.embedder import DEFAULT_MODEL, Embedder
from vector_index.index_builder import build_index, incremental_update


def main():
    parser = argparse.ArgumentParser(description="HMMWV RAG Vector Index Builder")
    parser.add_argument("--content-units", type=Path,
                        default=Path("output/ingestion/content-units.jsonl"))
    parser.add_argument("--index-dir", type=Path,
                        default=Path("output/vector_index"))
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help="HuggingFace model name for embeddings.")
    parser.add_argument("--device", type=str, default="cpu",
                        help="Device for embedding model (cpu or cuda).")
    parser.add_argument("--incremental", action="store_true",
                        help="Only embed and index new/changed units.")
    parser.add_argument("--force-rebuild", action="store_true",
                        help="Delete existing index and rebuild from scratch.")
    args = parser.parse_args()

    if not args.content_units.exists():
        print(f"[ERROR] Content units file not found: {args.content_units}", file=sys.stderr)
        print("Run `python -m ingestion.run_ingestion` first.", file=sys.stderr)
        sys.exit(1)

    embedder = Embedder(model_name=args.model, device=args.device)

    if args.incremental and not args.force_rebuild:
        incremental_update(args.content_units, args.index_dir, embedder)
    else:
        build_index(
            args.content_units,
            args.index_dir,
            embedder,
            force_rebuild=args.force_rebuild,
        )


if __name__ == "__main__":
    main()
