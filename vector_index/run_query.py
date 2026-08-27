"""
vector_index/run_query.py

CLI entrypoint for hybrid retrieval queries.

Usage:
    python -m vector_index.run_query \\
        --index-dir output/vector_index \\
        --query "engine does not start" \\
        [--filter manual_id=TM-9-2320-280-20-1] \\
        [--filter subsystem=engine] \\
        [--top-k 5] \\
        [--rerank]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vector_index.embedder import DEFAULT_MODEL, Embedder
from vector_index.retriever import HybridRetriever


def _parse_filters(filter_args: list[str]) -> dict:
    filters = {}
    for f in filter_args or []:
        if "=" not in f:
            print(f"[WARN] Ignoring malformed filter: {f!r} (expected key=value)")
            continue
        key, value = f.split("=", 1)
        filters[key.strip()] = value.strip()
    return filters


def main():
    parser = argparse.ArgumentParser(description="HMMWV RAG Hybrid Query")
    parser.add_argument("--index-dir", type=Path, default=Path("output/vector_index"))
    parser.add_argument("--content-units", type=Path,
                        default=Path("output/ingestion/content-units.jsonl"))
    parser.add_argument("--query", "-q", type=str, required=True)
    parser.add_argument("--filter", "-f", action="append", dest="filters",
                        help="Metadata filter in key=value format. Can be repeated.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=20,
                        help="Number of candidates per retrieval method before RRF.")
    parser.add_argument("--rerank", action="store_true",
                        help="Apply cross-encoder reranking (slower, higher quality).")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--device", type=str, default="cpu")
    args = parser.parse_args()

    if not (args.index_dir / "bm25_index.pkl").exists():
        print(f"[ERROR] Index not found at {args.index_dir}. Run run_indexer.py first.",
              file=sys.stderr)
        sys.exit(1)

    filters = _parse_filters(args.filters)
    embedder = Embedder(model_name=args.model, device=args.device)
    retriever = HybridRetriever.load(
        args.index_dir,
        embedder,
        content_units_path=args.content_units,
        top_n=args.top_n,
    )

    print(f"\nQuery : {args.query!r}")
    if filters:
        print(f"Filters: {filters}")
    print()

    results = retriever.retrieve(args.query, filters=filters or None, top_k=args.top_k)

    if args.rerank and results:
        from vector_index.reranker import CrossEncoderReranker
        reranker = CrossEncoderReranker(device=args.device)
        results = reranker.rerank(args.query, results)

    for r in results:
        sem = f"sem={r.semantic_rank}" if r.semantic_rank else "sem=-"
        bm = f"bm25={r.bm25_rank}" if r.bm25_rank else "bm25=-"
        print(f"[{r.rank}] {r.content_id}  score={r.rrf_score:.5f}  ({sem}, {bm}, {r.retrieval_source})")
        print(f"    Title      : {r.title}")
        print(f"    Manual     : {r.manual_id}  type={r.unit_type}")
        print(f"    Source     : {r.source_path}  #{r.anchor or '-'}")
        excerpt = r.text_plain[:300].replace("\n", " ")
        print(f"    Excerpt    : {excerpt}...")
        print()


if __name__ == "__main__":
    main()
