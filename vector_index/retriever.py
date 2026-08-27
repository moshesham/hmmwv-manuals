"""
vector_index/retriever.py

Hybrid retrieval: semantic (ChromaDB) + BM25 (rank_bm25) fused with RRF.

Usage:
    retriever = HybridRetriever.load(index_dir, embedder)
    results = retriever.retrieve("engine does not start", filters={"manual_role": "maintenance"})
"""
from __future__ import annotations

import json
import pickle
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from vector_index.embedder import Embedder, build_embed_text
from vector_index.metadata_schema import CHROMADB_COLLECTION, build_chroma_where

BM25_INDEX_FILENAME = "bm25_index.pkl"
UNIT_IDS_FILENAME = "unit_ids.json"
UNITS_FILENAME = "content-units.jsonl"

# RRF constant (standard value)
RRF_K = 60


@dataclass
class RetrievalResult:
    content_id: str
    rrf_score: float
    rank: int
    semantic_rank: Optional[int]
    bm25_rank: Optional[int]
    retrieval_source: str        # "semantic" | "bm25" | "both"
    title: str
    text_plain: str
    source_path: str
    anchor: Optional[str]
    manual_id: str
    unit_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+(?:[-/][a-zA-Z0-9]+)*", text.lower())


def _rrf_score(ranks: list[int], k: int = RRF_K) -> float:
    return sum(1.0 / (k + r) for r in ranks)


class HybridRetriever:
    """
    Combines dense semantic retrieval (ChromaDB) with sparse BM25 retrieval
    and merges results using Reciprocal Rank Fusion (RRF).
    """

    def __init__(
        self,
        chroma_dir: Path,
        bm25: Any,
        unit_ids: list[str],
        unit_map: dict[str, dict[str, Any]],
        embedder: Embedder,
        top_n: int = 20,
        rrf_k: int = RRF_K,
    ):
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError("chromadb is required.") from exc

        import chromadb as _chromadb

        self._client = _chromadb.PersistentClient(path=str(chroma_dir))
        self._collection = self._client.get_collection(name=CHROMADB_COLLECTION)
        self._bm25 = bm25
        self._unit_ids = unit_ids
        self._unit_map = unit_map
        self._embedder = embedder
        self.top_n = top_n
        self.rrf_k = rrf_k

    @classmethod
    def load(
        cls,
        index_dir: Path,
        embedder: Embedder,
        content_units_path: Optional[Path] = None,
        top_n: int = 20,
    ) -> "HybridRetriever":
        """
        Load an existing index from disk.
        content_units_path is used to restore the full unit dicts for result payloads.
        If not provided, falls back to index_dir/../ingestion/content-units.jsonl.
        """
        bm25_path = index_dir / BM25_INDEX_FILENAME
        unit_ids_path = index_dir / UNIT_IDS_FILENAME

        if not bm25_path.exists():
            raise FileNotFoundError(f"BM25 index not found at {bm25_path}. Run run_indexer.py first.")
        if not unit_ids_path.exists():
            raise FileNotFoundError(f"Unit IDs file not found at {unit_ids_path}.")

        with bm25_path.open("rb") as f:
            bm25 = pickle.load(f)

        unit_ids = json.loads(unit_ids_path.read_text(encoding="utf-8"))

        # Load full unit dicts for result payloads
        if content_units_path is None:
            content_units_path = index_dir.parent / "ingestion" / "content-units.jsonl"
        unit_map: dict[str, dict] = {}
        if content_units_path.exists():
            with content_units_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        u = json.loads(line)
                        unit_map[u["content_id"]] = u

        return cls(
            chroma_dir=index_dir / "chroma",
            bm25=bm25,
            unit_ids=unit_ids,
            unit_map=unit_map,
            embedder=embedder,
            top_n=top_n,
        )

    def retrieve(
        self,
        query: str,
        filters: Optional[dict[str, Any]] = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """
        Hybrid retrieval:
        1. Dense semantic query via ChromaDB (top_n results).
        2. BM25 keyword query (top_n results), post-filtered by metadata.
        3. RRF merge → return top_k.
        """
        t0 = time.perf_counter()

        # 1. Semantic retrieval
        where_clause = build_chroma_where(filters) if filters else None
        query_emb = self._embedder.embed_query(query)
        chroma_kwargs: dict[str, Any] = {
            "query_embeddings": [query_emb.tolist()],
            "n_results": min(self.top_n, self._collection.count()),
            "include": ["metadatas", "distances", "documents"],
        }
        if where_clause:
            chroma_kwargs["where"] = where_clause

        chroma_res = self._collection.query(**chroma_kwargs)
        semantic_ids: list[str] = chroma_res["ids"][0] if chroma_res["ids"] else []

        # 2. BM25 retrieval
        tokens = _tokenize(query)
        if tokens:
            scores = self._bm25.get_scores(tokens)
            ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            # Post-filter by metadata if filters provided
            if filters:
                bm25_ids_ordered = self._apply_metadata_filter(ranked_indices, filters)
            else:
                bm25_ids_ordered = [self._unit_ids[i] for i in ranked_indices
                                    if i < len(self._unit_ids)]
            bm25_ids = bm25_ids_ordered[:self.top_n]
        else:
            bm25_ids = []

        # 3. RRF fusion
        score_map: dict[str, dict] = {}
        for rank, cid in enumerate(semantic_ids, start=1):
            score_map.setdefault(cid, {"semantic_rank": None, "bm25_rank": None})
            score_map[cid]["semantic_rank"] = rank

        for rank, cid in enumerate(bm25_ids, start=1):
            score_map.setdefault(cid, {"semantic_rank": None, "bm25_rank": None})
            score_map[cid]["bm25_rank"] = rank

        rrf_scored: list[tuple[str, float]] = []
        for cid, ranks in score_map.items():
            active_ranks = [r for r in (ranks["semantic_rank"], ranks["bm25_rank"]) if r is not None]
            rrf_scored.append((cid, _rrf_score(active_ranks, self.rrf_k)))

        rrf_sorted = sorted(rrf_scored, key=lambda x: x[1], reverse=True)[:top_k]

        results: list[RetrievalResult] = []
        for rank, (cid, score) in enumerate(rrf_sorted, start=1):
            ranks_info = score_map[cid]
            sem_rank = ranks_info.get("semantic_rank")
            bm_rank = ranks_info.get("bm25_rank")
            source = "both" if (sem_rank and bm_rank) else ("semantic" if sem_rank else "bm25")

            unit = self._unit_map.get(cid, {})
            results.append(RetrievalResult(
                content_id=cid,
                rrf_score=round(score, 6),
                rank=rank,
                semantic_rank=sem_rank,
                bm25_rank=bm_rank,
                retrieval_source=source,
                title=unit.get("title", ""),
                text_plain=unit.get("text_plain", ""),
                source_path=unit.get("source", {}).get("path", ""),
                anchor=unit.get("source", {}).get("anchor"),
                manual_id=unit.get("manual_id", ""),
                unit_type=unit.get("unit_type", ""),
                metadata=unit.get("taxonomy", {}),
            ))

        elapsed = time.perf_counter() - t0
        return results

    def _apply_metadata_filter(
        self,
        ranked_indices: list[int],
        filters: dict[str, Any],
    ) -> list[str]:
        """
        Post-filter BM25 ranked indices against metadata filters.
        Uses the unit_map for metadata lookup.
        """
        results: list[str] = []
        for idx in ranked_indices:
            if idx >= len(self._unit_ids):
                continue
            cid = self._unit_ids[idx]
            unit = self._unit_map.get(cid, {})
            if self._matches_filters(unit, filters):
                results.append(cid)
        return results

    def _matches_filters(self, unit: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, value in filters.items():
            if key == "manual_id" and unit.get("manual_id") != value:
                return False
            if key == "manual_role" and unit.get("manual_role") != value:
                return False
            if key == "unit_type" and unit.get("unit_type") != value:
                return False
            if key == "has_warnings" and bool(unit.get("warnings")) != bool(value):
                return False
            if key == "subsystem":
                subsystem = unit.get("taxonomy", {}).get("subsystem") or ""
                if subsystem != value:
                    return False
        return True
